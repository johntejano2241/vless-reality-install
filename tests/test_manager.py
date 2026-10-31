import copy
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs

spec = importlib.util.spec_from_file_location('manager', Path(__file__).resolve().parents[1] / 'realityctl.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
NOW = datetime(2026, 10, 31, 4, 0, 0, tzinfo=timezone.utc)


def empty_config():
    config = m.make_config('example.com', 443, 'test-private-key')
    config['inbounds'][0]['streamSettings']['realitySettings']['shortIds'] = ['0123456789abcdef']
    return config


def empty_registry():
    return {'version': 1, 'clients': []}


class ClientRulesTests(unittest.TestCase):
    def test_no_expiry_and_finite_days(self):
        self.assertIsNone(m.expiry_from_days(0, NOW))
        record = {'expires_at': m.expiry_from_days(2, NOW)}
        self.assertEqual(m.client_status(record, NOW + timedelta(days=2, microseconds=-1)), 'active')
        self.assertEqual(m.client_status(record, NOW + timedelta(days=2)), 'expired')
        self.assertEqual(m.client_status({'expires_at': None}, NOW + timedelta(days=365)), 'active')
        self.assertEqual(m.display_expiry(record), '2026-11-02 12:00:00 +08:00')
        self.assertEqual(m.display_expiry({'expires_at': None}), 'Never')

    def test_invalid_days_and_names(self):
        for days in ['-1', '1.5', 'abc', '', True, '1e3', '+2']:
            with self.subTest(days=days), self.assertRaises(ValueError):
                m.parse_days(days)
        with self.assertRaises(ValueError):
            m.expiry_from_days(999999999999, NOW)
        for name in ['../root', 'a b', '', 'a\n', ';reboot', '-x']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                m.client_name(name)

    def test_duplicate_active_and_expired_names(self):
        registry = m.edit_clients(empty_registry(), 'add', 'Andrea', 1, NOW)
        for when in [NOW, NOW + timedelta(days=2)]:
            for name in ['Andrea', 'andrea', 'ANDREA']:
                with self.subTest(when=when, name=name), self.assertRaisesRegex(ValueError, 'already exists'):
                    m.edit_clients(registry, 'add', name, 0, when)

    def test_expire_retains_record_and_renew_preserves_link(self):
        registry = m.edit_clients(empty_registry(), 'add', 'andrea', 1, NOW)
        registry = m.edit_clients(registry, 'add', 'laptop', 0, NOW)
        config = empty_config()
        meta = {'endpoint': '203.0.113.1', 'publicKey': 'test-public-key'}
        record = m.find_client(registry, 'andrea')
        link = m.share_link(config, meta, record)
        later = NOW + timedelta(days=2)
        expired_config = m.render_config(config, registry, later)
        self.assertEqual([u['email'] for u in m.users(expired_config)], ['laptop'])
        self.assertEqual(len(registry['clients']), 2)
        self.assertEqual(m.client_status(m.find_client(registry, 'andrea'), later), 'expired')
        renewed = m.edit_clients(registry, 'renew', 'andrea', 3, later)
        self.assertEqual(m.share_link(config, meta, m.find_client(renewed, 'andrea')), link)
        self.assertEqual(m.find_client(renewed, 'andrea')['expires_at'], m.timestamp(later + timedelta(days=3)))
        self.assertEqual([u['email'] for u in m.users(m.render_config(config, renewed, later))], ['andrea', 'laptop'])
        parsed = urlsplit(link)
        self.assertEqual(parse_qs(parsed.query)['security'], ['reality'])
        self.assertEqual(parse_qs(parsed.query)['flow'], ['xtls-rprx-vision'])

    def test_renew_to_no_expiry(self):
        registry = m.edit_clients(empty_registry(), 'add', 'phone', 1, NOW)
        renewed = m.edit_clients(registry, 'renew', 'phone', 0, NOW + timedelta(days=1))
        self.assertIsNone(m.find_client(renewed, 'phone')['expires_at'])

    def test_renew_only_expired_existing_clients(self):
        registry = m.edit_clients(empty_registry(), 'add', 'phone', 0, NOW)
        with self.assertRaisesRegex(ValueError, 'only expired'):
            m.edit_clients(registry, 'renew', 'phone', 2, NOW)
        for action in ['renew', 'remove']:
            with self.assertRaisesRegex(ValueError, 'not found'):
                m.edit_clients(registry, action, 'missing', 0, NOW)

    def test_remove_expired_client_is_explicit(self):
        registry = m.edit_clients(empty_registry(), 'add', 'phone', 1, NOW)
        removed = m.edit_clients(registry, 'remove', 'phone', None, NOW + timedelta(days=2))
        self.assertEqual(removed['clients'], [])
        self.assertEqual(len(registry['clients']), 1)

    def test_legacy_migration_preserves_identities_and_options(self):
        config = empty_config()
        config['inbounds'][0]['settings']['clients'] = [
            {'id': 'existing-uuid', 'email': 'andrea', 'flow': 'xtls-rprx-vision', 'level': 1}]
        original = copy.deepcopy(config)
        migrated = m.registry_from_config(config)
        self.assertIsNone(migrated['clients'][0]['expires_at'])
        self.assertEqual(m.render_config(config, migrated, NOW), original)
        self.assertEqual(config, original)

    def test_bad_registry_is_not_treated_as_empty(self):
        for bad in [{}, {'version': 1, 'clients': 'bad'}, {'version': 1, 'clients': [{}]}]:
            with self.assertRaises(ValueError):
                m.validate_registry(bad)

    def test_input_validation(self):
        for host in ['https://example.com', 'a;sh', '-bad.com', 'a..com', 'a:443']:
            with self.assertRaises(ValueError):
                m.hostname(host)
        self.assertEqual(m.endpoint('203.0.113.1'), '203.0.113.1')


class DiskLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.multiple(m, ROOT=root, CONFIG=root / 'config.json', REGISTRY=root / 'clients.json', LOCK=root / 'manager.lock'))
        self.stack.enter_context(patch.object(m, 'utcnow', return_value=NOW))
        self.stack.enter_context(patch.object(m.os, 'geteuid', return_value=0))
        self.stack.enter_context(patch.object(m.os, 'fchown'))
        self.stack.enter_context(patch.object(m.grp, 'getgrnam', return_value=SimpleNamespace(gr_gid=os.getgid())))
        self.run = self.stack.enter_context(patch.object(m.subprocess, 'run'))
        m.CONFIG.write_text(json.dumps(empty_config()))
        (m.ROOT / 'server.json').write_text(json.dumps({'endpoint': '203.0.113.1', 'publicKey': 'test-public-key'}))
        self.output = self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.errors = self.stack.enter_context(redirect_stderr(io.StringIO()))

    def registry(self):
        return json.loads(m.REGISTRY.read_text())

    def config(self):
        return json.loads(m.CONFIG.read_text())

    def test_cli_add_find_list_remove(self):
        m.main(['add', 'phone', '--days', '0'])
        identity = m.users(self.config())[0]['id']
        self.assertEqual(m.REGISTRY.stat().st_mode & 0o777, 0o600)
        self.assertEqual(m.CONFIG.stat().st_mode & 0o777, 0o640)
        m.main(['find', 'phone'])
        m.main(['list'])
        self.assertIn(identity, self.output.getvalue())
        self.assertIn('active', self.output.getvalue())
        self.assertIn('Never', self.output.getvalue())
        m.main(['remove', 'phone'])
        self.assertEqual(self.registry()['clients'], [])
        self.assertEqual(m.users(self.config()), [])

    def test_timer_retains_expired_record_and_same_link_renews(self):
        m.execute('add', 'andrea', 1)
        original = copy.deepcopy(self.registry()['clients'][0])
        link = m.share_link(self.config(), json.loads((m.ROOT / 'server.json').read_text()), original)
        later = NOW + timedelta(days=2)
        with patch.object(m, 'utcnow', return_value=later):
            m.main(['expire'])
            self.assertEqual(m.users(self.config()), [])
            self.assertEqual(self.registry()['clients'], [original])
            m.main(['find', 'andrea'])
            self.assertIn('expired', self.output.getvalue())
            m.main(['renew', 'andrea', '--days', '0'])
        self.assertEqual(m.users(self.config())[0]['id'], original['user']['id'])
        renewed = self.registry()['clients'][0]
        self.assertIsNone(renewed['expires_at'])
        self.assertEqual(m.share_link(self.config(), json.loads((m.ROOT / 'server.json').read_text()), renewed), link)

    def test_no_changes_do_not_restart_active_clients(self):
        m.execute('add', 'phone', 0)
        self.run.reset_mock()
        for command in ['expire', 'list', 'find']:
            m.execute(command, 'phone' if command == 'find' else None)
        self.run.assert_not_called()

    def test_validation_failure_keeps_both_files(self):
        m.execute('add', 'phone', 0)
        original_config, original_registry = m.CONFIG.read_bytes(), m.REGISTRY.read_bytes()
        self.run.side_effect = subprocess.CalledProcessError(1, 'xray')
        with self.assertRaises(subprocess.CalledProcessError):
            m.execute('add', 'laptop', 1)
        self.assertEqual(m.CONFIG.read_bytes(), original_config)
        self.assertEqual(m.REGISTRY.read_bytes(), original_registry)
        self.assertFalse((m.ROOT / 'candidate.json').exists())

    def test_restart_failure_restores_both_files(self):
        m.execute('add', 'phone', 0)
        original_config, original_registry = self.config(), self.registry()
        self.run.side_effect = [None, subprocess.CalledProcessError(1, 'restart'), None, None]
        with self.assertRaisesRegex(RuntimeError, 'previous client records'):
            m.execute('remove', 'phone')
        self.assertEqual(self.config(), original_config)
        self.assertEqual(self.registry(), original_registry)
        self.assertFalse((m.ROOT / 'candidate.json').exists())

    def test_failed_expiry_is_retried_without_losing_records(self):
        m.execute('add', 'phone', 1)
        later = NOW + timedelta(days=2)
        with patch.object(m, 'utcnow', return_value=later):
            self.run.side_effect = [None, subprocess.CalledProcessError(1, 'restart'), None, None]
            with self.assertRaises(RuntimeError):
                m.execute('expire')
            self.assertEqual(len(self.registry()['clients']), 1)
            self.run.side_effect = None
            m.execute('expire')
        self.assertEqual(m.users(self.config()), [])
        self.assertEqual(len(self.registry()['clients']), 1)

    def test_timer_recovers_registry_published_before_crash(self):
        m.execute('add', 'phone', 0)
        # Simulate a process dying after publishing a removal but before replacing config.
        m.atomic_json(m.REGISTRY, empty_registry())
        self.assertEqual(len(m.users(self.config())), 1)
        m.execute('expire')
        self.assertEqual(m.users(self.config()), [])

    def test_corrupt_records_do_not_clear_runtime_clients(self):
        m.execute('add', 'phone', 0)
        original = m.CONFIG.read_bytes()
        m.REGISTRY.write_text('{broken')
        with self.assertRaises(ValueError):
            m.execute('expire')
        self.assertEqual(m.CONFIG.read_bytes(), original)

    def test_migrate_is_idempotent_and_keeps_existing_link_data(self):
        config = self.config()
        config['inbounds'][0]['settings']['clients'] = [{'id': 'keep-this-uuid', 'email': 'andrea', 'flow': 'xtls-rprx-vision'}]
        m.CONFIG.write_text(json.dumps(config))
        original_config, original_meta = m.CONFIG.read_bytes(), (m.ROOT / 'server.json').read_bytes()
        m.main(['migrate'])
        m.main(['migrate'])
        self.assertEqual(self.registry()['clients'][0]['user']['id'], 'keep-this-uuid')
        self.assertIsNone(self.registry()['clients'][0]['expires_at'])
        self.assertEqual(m.CONFIG.read_bytes(), original_config)
        self.assertEqual((m.ROOT / 'server.json').read_bytes(), original_meta)
        self.run.assert_not_called()

    def test_command_aliases(self):
        m.main(['add', 'phone', '--days', '0'])
        m.main(['show', 'phone'])
        m.main(['all'])
        m.main(['revoke', 'phone'])
        self.assertEqual(self.registry()['clients'], [])

    def test_menu_add_find_list_remove_and_duplicate_error(self):
        inputs = ['1', 'andrea', '0', '0', '1', 'ANDREA', '1', '0', '3', 'andrea', '4', '5', 'andrea', 'y', '0']
        with patch('builtins.input', side_effect=inputs):
            m.main([])
        self.assertIn('already exists', self.errors.getvalue())
        self.assertIn('Name', self.output.getvalue())
        self.assertIn('Never', self.output.getvalue())
        self.assertEqual(self.registry()['clients'], [])

    def test_menu_invalid_days_and_cancelled_removal(self):
        m.execute('add', 'phone', 0)
        with patch('builtins.input', side_effect=['1', 'bad', '-1', '5', 'phone', 'n', '0']):
            m.main(['menu'])
        self.assertIn('Days must be', self.errors.getvalue())
        self.assertEqual([c['name'] for c in self.registry()['clients']], ['phone'])

    def test_menu_renew_expired_client(self):
        m.execute('add', 'phone', 1)
        with patch.object(m, 'utcnow', return_value=NOW + timedelta(days=2)), \
             patch('builtins.input', side_effect=['2', 'phone', '4', '0']):
            m.main(['menu'])
        self.assertEqual(self.registry()['clients'][0]['expires_at'], m.timestamp(NOW + timedelta(days=6)))

    def test_automation_requires_explicit_days(self):
        with patch.object(m.sys.stdin, 'isatty', return_value=False):
            with self.assertRaisesRegex(ValueError, 'Supply --days'):
                m.main(['add', 'phone'])
        self.assertFalse(m.REGISTRY.exists())

    def test_lock_rejects_symlinks_without_touching_the_target(self):
        target = m.ROOT / 'unrelated.txt'
        target.write_text('keep this data')
        m.LOCK.symlink_to(target)
        with self.assertRaises(OSError):
            with m.locked():
                self.fail('A symlink lock must not be acquired')
        self.assertEqual(target.read_text(), 'keep this data')


if __name__ == '__main__':
    unittest.main()

