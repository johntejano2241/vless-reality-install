import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs

spec = importlib.util.spec_from_file_location('manager', Path(__file__).resolve().parents[1] / 'realityctl.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.config = m.make_config('example.com', 443, 'test-private-key')
        self.config['inbounds'][0]['streamSettings']['realitySettings']['shortIds'] = ['0123456789abcdef']

    def test_add_show_revoke(self):
        m.change(self.config, 'add', 'phone')
        m.change(self.config, 'add', 'laptop')
        self.assertNotEqual(*[u['id'] for u in m.users(self.config)])
        link = urlsplit(m.share_link(self.config, {'endpoint': '203.0.113.1', 'publicKey': 'test-public'}, 'phone'))
        self.assertEqual(link.hostname, '203.0.113.1')
        self.assertEqual(parse_qs(link.query)['security'], ['reality'])
        revoked = m.users(self.config)[0]['id']
        m.change(self.config, 'revoke', 'phone')
        self.assertNotIn(revoked, json.dumps(self.config))
        self.assertEqual([u['email'] for u in m.users(self.config)], ['laptop'])
        with self.assertRaises(ValueError):
            m.share_link(self.config, {'endpoint': 'example.com', 'publicKey': 'key'}, 'phone')

    def test_invalid_and_duplicate_names(self):
        for name in ['../root', 'a b', '', 'a\n', ';reboot', '-x']:
            with self.assertRaises(ValueError):
                m.client_name(name)
        m.change(self.config, 'add', 'phone')
        with self.assertRaises(ValueError):
            m.change(self.config, 'add', 'phone')
        with self.assertRaises(ValueError):
            m.change(self.config, 'revoke', 'missing')

    def test_input_validation(self):
        for host in ['https://example.com', 'a;sh', '-bad.com', 'a..com', 'a:443']:
            with self.assertRaises(ValueError):
                m.hostname(host)
        self.assertEqual(m.endpoint('203.0.113.1'), '203.0.113.1')
        self.assertEqual(m.hostname('www.microsoft.com'), 'www.microsoft.com')

    def test_failed_validation_preserves_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conf = root / 'config.json'
            conf.write_text(json.dumps(self.config))
            original = conf.read_bytes()
            def writer(path, data, service_readable=False):
                path.write_text(json.dumps(data))
            with patch.object(m, 'ROOT', root), patch.object(m, 'CONFIG', conf), \
                 patch.object(m, 'atomic_json', side_effect=writer), \
                 patch.object(m.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'xray')):
                with self.assertRaises(subprocess.CalledProcessError):
                    m.commit(m.change(copy.deepcopy(self.config), 'add', 'phone'))
            self.assertEqual(conf.read_bytes(), original)
            self.assertFalse((root / 'candidate.json').exists())

    def test_failed_restart_restores_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conf = root / 'config.json'
            conf.write_text(json.dumps(self.config))
            def writer(path, data, service_readable=False):
                path.write_text(json.dumps(data))
            calls = [None, subprocess.CalledProcessError(1, 'systemctl'), None]
            with patch.object(m, 'ROOT', root), patch.object(m, 'CONFIG', conf), \
                 patch.object(m, 'atomic_json', side_effect=writer), \
                 patch.object(m.subprocess, 'run', side_effect=calls):
                with self.assertRaises(RuntimeError):
                    m.commit(m.change(copy.deepcopy(self.config), 'add', 'phone'))
            self.assertEqual(json.loads(conf.read_text()), self.config)


if __name__ == '__main__':
    unittest.main()
