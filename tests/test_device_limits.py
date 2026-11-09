from contextlib import ExitStack, redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import realityctl as m
import ip_limiter as limiter

NOW = datetime(2026, 10, 31, 4, 0, 0, tzinfo=timezone.utc)
EPOCH = NOW.timestamp()
IP1, IP2, IP3 = '198.51.100.1', '198.51.100.2', '198.51.100.3'


def client_registry(limit=1):
    return m.edit_clients({'version': 1, 'clients': []}, 'add', 'andrea', 0, NOW, devices=limit)


def state_for(registry, addresses):
    return {'version': 1, 'clients': {registry['clients'][0]['user']['id']: addresses}}


class SlotPolicyTests(unittest.TestCase):
    def test_zero_is_unlimited_and_positive_limits_are_valid(self):
        self.assertEqual(m.parse_devices('0'), 0)
        self.assertEqual(m.parse_devices('12'), 12)
        for value in ['-1', '1.5', '', 'abc', '+1', True, None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                m.parse_devices(value)
        registry = client_registry(0)
        result = limiter.choose_slots(registry, {'clients': {}}, {'andrea': {IP1, IP2}}, [('andrea', IP3)], EPOCH)
        self.assertEqual(result['clients'], {})

    def test_two_prompts_produce_two_distinct_settings(self):
        registry = m.edit_clients({'version': 1, 'clients': []}, 'add', 'phone', 7, NOW, devices=2)
        record = registry['clients'][0]
        self.assertEqual(record['device_limit'], 2)
        self.assertEqual(record['expires_at'], m.timestamp(NOW + timedelta(days=7)))

    def test_first_ip_admitted_then_second_ip_refused(self):
        registry = client_registry(1)
        first = limiter.choose_slots(registry, {'clients': {}}, {}, [('andrea', IP1)], EPOCH)
        second = limiter.choose_slots(registry, first, {'andrea': {IP1}}, [('andrea', IP2)], EPOCH + 1)
        self.assertEqual(set(next(iter(second['clients'].values()))), {IP1})

    def test_same_ip_on_multiple_devices_uses_one_slot(self):
        registry = client_registry(1)
        result = limiter.choose_slots(registry, {'clients': {}}, {},
            [('andrea', IP1), ('ANDREA', IP1), ('andrea', '::ffff:' + IP1)], EPOCH)
        self.assertEqual(set(next(iter(result['clients'].values()))), {IP1})

    def test_two_slots_accept_two_ips_and_refuse_third(self):
        registry = client_registry(2)
        result = limiter.choose_slots(registry, {'clients': {}}, {},
            [('andrea', IP1), ('andrea', IP2), ('andrea', IP3)], EPOCH)
        self.assertEqual(set(next(iter(result['clients'].values()))), {IP1, IP2})

    def test_live_long_stream_keeps_slot_past_idle_grace(self):
        registry = client_registry(1)
        old = state_for(registry, {IP1: EPOCH})
        result = limiter.choose_slots(registry, old, {'andrea': {IP1}}, [('andrea', IP2)], EPOCH + 3600)
        self.assertEqual(set(next(iter(result['clients'].values()))), {IP1})

    def test_disconnected_slot_released_after_grace(self):
        registry = client_registry(1)
        old = state_for(registry, {IP1: EPOCH})
        held = limiter.choose_slots(registry, old, {}, [('andrea', IP2)], EPOCH + limiter.IDLE_GRACE_SECONDS)
        self.assertEqual(set(next(iter(held['clients'].values()))), {IP1})
        released = limiter.choose_slots(registry, held, {}, [('andrea', IP2)], EPOCH + limiter.IDLE_GRACE_SECONDS + 1)
        self.assertEqual(set(next(iter(released['clients'].values()))), {IP2})

    def test_limits_are_independent_for_accounts_sharing_an_ip(self):
        registry = client_registry(1)
        registry = m.edit_clients(registry, 'add', 'other', 0, NOW, devices=2)
        result = limiter.choose_slots(registry, {'clients': {}}, {},
            [('andrea', IP1), ('andrea', IP2), ('other', IP1), ('other', IP2)], EPOCH)
        first, second = [r['user']['id'] for r in registry['clients']]
        self.assertEqual(set(result['clients'][first]), {IP1})
        self.assertEqual(set(result['clients'][second]), {IP1, IP2})

    def test_ambiguous_live_sample_does_not_displace_an_admitted_ip(self):
        registry = client_registry(1)
        result = limiter.choose_slots(registry, state_for(registry, {IP2: EPOCH}),
            {'andrea': {IP1, IP2}}, [('andrea', IP1)], EPOCH + 1)
        self.assertEqual(set(next(iter(result['clients'].values()))), {IP2})
        unknown = limiter.choose_slots(registry, {'clients': {}}, {'andrea': {IP1, IP2}}, [], EPOCH)
        self.assertEqual(next(iter(unknown['clients'].values())), {})

    def test_expired_clients_keep_their_records_but_lose_slots(self):
        registry = m.edit_clients({'version': 1, 'clients': []}, 'add', 'andrea', 1, NOW, devices=1)
        result = limiter.choose_slots(registry, state_for(registry, {IP1: EPOCH}),
            {'andrea': {IP1}}, [('andrea', IP2)], EPOCH + 86401)
        self.assertEqual(result['clients'], {})
        self.assertEqual(len(registry['clients']), 1)
        renewed = m.edit_clients(registry, 'renew', 'andrea', 0, NOW + timedelta(days=2))
        self.assertEqual(renewed['clients'][0]['device_limit'], 1)
        self.assertEqual(renewed['clients'][0]['user']['id'], registry['clients'][0]['user']['id'])

    def test_source_parsing_and_ipv4_mapped_normalization(self):
        self.assertEqual(limiter.source_ip(IP1 + ':12345'), IP1)
        self.assertEqual(limiter.source_ip('[::ffff:' + IP1 + ']:443'), IP1)
        self.assertEqual(limiter.source_ip('[2001:db8::1]:443'), '2001:db8::1')
        for value in ['bad:443', IP1, IP1 + ':0', IP1 + ':65536', None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                limiter.source_ip(value)

    def test_rules_are_per_identity_and_keep_destination_security_first(self):
        registry = client_registry(1)
        config = m.make_config('example.com', 443, 'test-key')
        original_block = config['routing']['rules'][0]
        identity = registry['clients'][0]['user']['id']
        routing = m.ip_routing(config, registry, NOW, {identity: {IP1: EPOCH}})
        self.assertEqual(routing['rules'][0], original_block)
        allow, deny = routing['rules'][1:]
        self.assertEqual(allow['sourceIP'], [IP1])
        for rule in [allow, deny]:
            self.assertEqual(rule['user'], ['andrea'])
            self.assertEqual(rule['inboundTag'], ['reality'])
        self.assertEqual(deny['outboundTag'], 'blocked')
        self.assertEqual(deny['webhook']['url'], m.EVENT_SOCKET)
        # Disk config is fail-closed until the controller admits an IP.
        disk = m.render_config(config, registry, NOW)
        self.assertFalse(any(r.get('outboundTag') == 'direct' for r in disk['routing']['rules']))
        self.assertEqual(m.render_config(disk, registry, NOW), disk)
        self.assertEqual(disk['api']['listen'], m.API_SOCKET)

    def test_no_unsupported_device_field_is_passed_to_xray(self):
        registry = client_registry(2)
        rendered = m.render_config(m.make_config('example.com', 443, 'key'), registry, NOW)
        self.assertNotIn('device_limit', rendered['inbounds'][0]['settings']['clients'][0])
        self.assertEqual(rendered['policy']['levels']['0']['statsUserOnline'], True)


class DeviceManagerDiskTests(unittest.TestCase):
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
        config = m.enable_ip_control(m.make_config('example.com', 443, 'key'), {'clients': []})
        config['inbounds'][0]['streamSettings']['realitySettings']['shortIds'] = ['0123456789abcdef']
        m.CONFIG.write_text(json.dumps(config))
        (m.ROOT / 'server.json').write_text(json.dumps({'endpoint': '203.0.113.1', 'publicKey': 'test-public-key'}))
        self.output = self.stack.enter_context(redirect_stdout(io.StringIO()))

    def test_menu_prompts_for_expiry_before_devices(self):
        with patch('builtins.input', side_effect=['1', 'andrea', '7', '2', '0']) as inputs:
            m.main(['menu'])
        prompts = [call.args[0] for call in inputs.call_args_list]
        self.assertIn('Expiration days', prompts[2])
        self.assertIn('Public-IP slots', prompts[3])
        record = json.loads(m.REGISTRY.read_text())['clients'][0]
        self.assertEqual(record['device_limit'], 2)
        self.assertEqual(record['expires_at'], m.timestamp(NOW + timedelta(days=7)))
        self.assertIn('IP slots', self.output.getvalue())

    def test_cli_devices_option_and_legacy_default(self):
        m.main(['add', 'phone', '--days', '0', '--devices', '1'])
        m.main(['add', 'laptop', '--days', '0'])
        m.main(['add', 'tablet', '--days', '0', '--ip-limit', '2'])
        records = json.loads(m.REGISTRY.read_text())['clients']
        self.assertEqual([r['device_limit'] for r in records], [1, 0, 2])

    def test_set_limit_on_existing_unlimited_account_preserves_link_and_expiry(self):
        m.main(['add', 'phone', '--days', '7'])
        original = json.loads(m.REGISTRY.read_text())['clients'][0]
        config = json.loads(m.CONFIG.read_text())
        meta = json.loads((m.ROOT / 'server.json').read_text())
        link = m.share_link(config, meta, original)
        m.main(['set-limit', 'PHONE', '--ips', '1'])
        updated = json.loads(m.REGISTRY.read_text())['clients'][0]
        self.assertEqual(updated, dict(original, device_limit=1))
        self.assertEqual(m.share_link(json.loads(m.CONFIG.read_text()), meta, updated), link)
        self.assertTrue(any(r.get('user') == ['phone'] and r['outboundTag'] == 'blocked'
                            for r in json.loads(m.CONFIG.read_text())['routing']['rules']))

    def test_reducing_a_positive_limit_restarts_to_clear_runtime_allowances(self):
        m.main(['add', 'phone', '--days', '0', '--devices', '2'])
        original_config = m.CONFIG.read_bytes()
        with patch.object(m, 'restart_service') as restart:
            m.main(['set-limit', 'phone', '--ips', '1'])
        restart.assert_called_once_with()
        self.assertEqual(m.CONFIG.read_bytes(), original_config)
        self.assertEqual(json.loads(m.REGISTRY.read_text())['clients'][0]['device_limit'], 1)

    def test_noop_limit_does_not_restart_and_zero_removes_guards(self):
        m.main(['add', 'phone', '--days', '0', '--devices', '1'])
        with patch.object(m, 'restart_service') as restart:
            m.main(['set-limit', 'phone', '--ips', '1'])
        restart.assert_not_called()
        m.main(['set-limit', 'phone', '--ips', '0'])
        self.assertFalse(any(r.get('user') == ['phone']
                             for r in json.loads(m.CONFIG.read_text())['routing']['rules']))

    def test_expired_account_limit_can_change_without_renewal(self):
        m.main(['add', 'phone', '--days', '1'])
        with patch.object(m, 'utcnow', return_value=NOW + timedelta(days=2)):
            m.main(['set-limit', 'phone', '--ips', '1'])
        record = json.loads(m.REGISTRY.read_text())['clients'][0]
        self.assertEqual(record['device_limit'], 1)
        self.assertEqual(record['expires_at'], m.timestamp(NOW + timedelta(days=1)))
        self.assertEqual(m.users(json.loads(m.CONFIG.read_text())), [])

    def test_bad_limit_missing_client_and_unavailable_controller_preserve_state(self):
        m.main(['add', 'phone', '--days', '0'])
        original = (m.CONFIG.read_bytes(), m.REGISTRY.read_bytes())
        for name, ips in [('phone', '-1'), ('missing', '1')]:
            with self.subTest(name=name, ips=ips), self.assertRaises(ValueError):
                m.main(['set-limit', name, '--ips', ips])
            self.assertEqual((m.CONFIG.read_bytes(), m.REGISTRY.read_bytes()), original)
        with patch.object(m.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'systemctl')):
            with self.assertRaisesRegex(ValueError, 'service is unavailable'):
                m.main(['set-limit', 'phone', '--ips', '1'])
        self.assertEqual((m.CONFIG.read_bytes(), m.REGISTRY.read_bytes()), original)

    def test_limit_restart_failure_restores_previous_cap(self):
        m.main(['add', 'phone', '--days', '0', '--devices', '2'])
        original = (m.CONFIG.read_bytes(), m.REGISTRY.read_bytes())
        with patch.object(m, 'restart_service', side_effect=[OSError('failed'), None]):
            with self.assertRaisesRegex(RuntimeError, 'previous client records'):
                m.main(['set-limit', 'phone', '--ips', '1'])
        self.assertEqual((m.CONFIG.read_bytes(), m.REGISTRY.read_bytes()), original)

    def test_menu_can_edit_existing_limit(self):
        m.main(['add', 'phone', '--days', '0'])
        with patch('builtins.input', side_effect=['6', 'phone', '1', '0']):
            m.main(['menu'])
        self.assertEqual(json.loads(m.REGISTRY.read_text())['clients'][0]['device_limit'], 1)

    def test_diagnostics_explain_same_ip_sharing_and_do_not_print_credentials(self):
        m.main(['add', 'phone', '--days', '0', '--devices', '1'])
        record = json.loads(m.REGISTRY.read_text())['clients'][0]
        original = (m.CONFIG.read_bytes(), m.REGISTRY.read_bytes())
        self.output.truncate(0)
        self.output.seek(0)
        with patch.object(limiter, 'online_ips', return_value={'phone': {IP1}}), \
             patch.object(limiter, 'read_state', return_value=state_for({'clients': [record]}, {IP1: EPOCH})):
            m.main(['limits', 'PHONE'])
        output = self.output.getvalue()
        self.assertIn('same Wi-Fi/hotspot', output)
        self.assertIn('Public IPs reported by Xray: ' + IP1, output)
        self.assertIn('Saved admitted IP slots: ' + IP1, output)
        self.assertNotIn(record['user']['id'], output)
        self.assertNotIn('vless://', output)
        self.assertEqual((m.CONFIG.read_bytes(), m.REGISTRY.read_bytes()), original)

    def test_diagnostics_report_unlimited_and_fail_visibly_if_stats_are_unavailable(self):
        m.main(['add', 'phone', '--days', '0'])
        with patch.object(limiter, 'online_ips', return_value={}), \
             patch.object(limiter, 'read_state', return_value={'clients': {}}):
            m.main(['limits', 'phone'])
        self.assertIn('This account is unlimited', self.output.getvalue())
        with patch.object(limiter, 'online_ips', side_effect=ValueError('unavailable')):
            with self.assertRaisesRegex(ValueError, 'Cannot read IP-limit diagnostics'):
                m.main(['limits', 'phone'])

    def test_expiry_registry_migration_preserves_existing_dates_and_ids(self):
        record = {'name': 'andrea', 'user': {'email': 'andrea', 'id': 'existing-id', 'flow': 'xtls-rprx-vision'}, 'expires_at': m.timestamp(NOW + timedelta(days=3))}
        m.REGISTRY.write_text(json.dumps({'version': 1, 'clients': [record]}))
        m.main(['migrate'])
        migrated = json.loads(m.REGISTRY.read_text())['clients'][0]
        self.assertEqual(migrated['device_limit'], 0)
        self.assertEqual(migrated['user'], record['user'])
        self.assertEqual(migrated['expires_at'], record['expires_at'])

    def test_api_failure_does_not_publish_new_slot_state(self):
        m.execute('add', 'phone', 0, devices=1)
        state = m.ROOT / 'slots.json'
        with patch.object(limiter, 'STATE', state), patch.object(limiter, 'online_ips', side_effect=ValueError('API unavailable')):
            with self.assertRaises(ValueError):
                limiter.reconcile([('phone', IP1)])
        self.assertFalse(state.exists())

    def test_runtime_update_does_not_write_admissions_to_disk_config(self):
        m.execute('add', 'phone', 0, devices=1)
        original = m.CONFIG.read_bytes()
        state = m.ROOT / 'slots.json'
        with patch.object(limiter, 'STATE', state), patch.object(limiter, 'online_ips', return_value={}), patch.object(limiter, 'api') as api:
            limiter.reconcile([('phone', IP1)])
        self.assertEqual(m.CONFIG.read_bytes(), original)
        self.assertIn(IP1, state.read_text())
        routing = json.loads(api.call_args.kwargs['input_text'])['routing']
        self.assertTrue(any(r.get('sourceIP') == [IP1] for r in routing['rules']))

    def test_pending_removal_never_drops_guards_before_authentication_updates(self):
        m.execute('add', 'phone', 0, devices=1)
        m.atomic_json(m.REGISTRY, {'version': 1, 'clients': []})
        with patch.object(limiter, 'api') as api:
            with self.assertRaisesRegex(ValueError, 'authentication update'):
                limiter.reconcile([])
        api.assert_not_called()


if __name__ == '__main__':
    unittest.main()

