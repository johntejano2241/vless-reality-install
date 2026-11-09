from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import admin_agent as agent
import realityctl as m

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


class AdminAgentTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.multiple(m, ROOT=self.root, CONFIG=self.root/'config.json', REGISTRY=self.root/'clients.json', LOCK=self.root/'manager.lock'))
        self.stack.enter_context(patch.object(m, 'utcnow', return_value=NOW))
        self.stack.enter_context(patch.object(m.os, 'fchown'))
        self.stack.enter_context(patch.object(m.grp, 'getgrnam', return_value=SimpleNamespace(gr_gid=os.getgid())))
        self.run = self.stack.enter_context(patch.object(m.subprocess, 'run'))
        self.run.return_value = SimpleNamespace(stdout='active\n', returncode=0)
        config=m.enable_ip_control(m.make_config('example.com',18443,'synthetic-private-key'), {'clients':[]})
        config['inbounds'][0]['streamSettings']['realitySettings']['shortIds']=['0123456789abcdef']
        m.CONFIG.write_text(json.dumps(config))
        m.REGISTRY.write_text(json.dumps({'version':1,'clients':[]}))
        (self.root/'server.json').write_text(json.dumps({'endpoint':'203.0.113.1','publicKey':'synthetic-public-key'}))

    def operation(self, action='add', name='phone', days=30, devices=1):
        payload={'operation_id':str(uuid.uuid4()),'action':action,'name':name,'days':days,'devices':devices}
        registry=json.loads(m.REGISTRY.read_text())
        if action!='add': payload['expected_version']=agent.version(m.find_client(registry,name))
        return payload

    def test_applied_operations_are_idempotent_in_the_authoritative_registry(self):
        payload=self.operation()
        result=agent.mutate(payload)
        self.run.reset_mock()
        self.assertEqual(agent.mutate(payload),result)
        self.run.assert_not_called()
        registry=json.loads(m.REGISTRY.read_text())
        self.assertEqual(len(registry['clients']),1)
        self.assertIn(payload['operation_id'],registry['admin_operations'])
        self.assertNotIn('id',result)

    def test_reusing_operation_id_with_different_payload_is_rejected(self):
        payload=self.operation(); agent.mutate(payload); payload['name']='another'
        with self.assertRaisesRegex(ValueError,'already used'): agent.mutate(payload)

    def test_active_renewal_extends_once_without_rotating_credential(self):
        agent.mutate(self.operation(days=10))
        before=json.loads(m.REGISTRY.read_text())['clients'][0]
        payload=self.operation('extend',days=5); agent.mutate(payload); agent.mutate(payload)
        after=json.loads(m.REGISTRY.read_text())['clients'][0]
        self.assertEqual(after['user'],before['user'])
        self.assertEqual(after['expires_at'],m.timestamp(NOW+timedelta(days=15)))

    def test_stale_renewal_cannot_undo_a_newer_suspension(self):
        agent.mutate(self.operation())
        stale=self.operation('extend')
        agent.mutate(self.operation('suspend'))
        with self.assertRaisesRegex(ValueError,'changed'): agent.mutate(stale)
        self.assertEqual(m.users(json.loads(m.CONFIG.read_text())),[])
        record=json.loads(m.REGISTRY.read_text())['clients'][0]
        self.assertEqual(m.client_status(record,NOW),'suspended')

    def test_extend_suspended_account_does_not_resume_access(self):
        agent.mutate(self.operation()); agent.mutate(self.operation('suspend'))
        agent.mutate(self.operation('extend',days=1))
        self.assertEqual(m.users(json.loads(m.CONFIG.read_text())),[])

    def test_rotation_changes_uuid_but_not_expiry_and_excess_permissions_are_rejected(self):
        agent.mutate(self.operation())
        before=json.loads(m.REGISTRY.read_text())['clients'][0]
        agent.mutate(self.operation('rotate'))
        after=json.loads(m.REGISTRY.read_text())['clients'][0]
        self.assertNotEqual(before['user']['id'],after['user']['id'])
        self.assertEqual(before['expires_at'],after['expires_at'])
        for extra in [{'command':'reboot'},{'path':'/etc/shadow'}]:
            with self.assertRaises(ValueError): agent.mutate(dict(self.operation(),**extra))

    def test_snapshot_contains_no_vless_uuid_or_private_key(self):
        agent.mutate(self.operation())
        identity=json.loads(m.REGISTRY.read_text())['clients'][0]['user']['id']
        with patch.object(agent.ip_limiter,'online_ips',return_value={}), patch.object(agent.ip_limiter,'api',return_value='{}'):
            result=agent.snapshot()
        serialized=json.dumps(result)
        self.assertNotIn(identity,serialized)
        self.assertNotIn('synthetic-private-key',serialized)
        self.assertIsNone(result['clients'][0].get('user'))

    def test_stats_failure_is_unknown_instead_of_zero_and_does_not_drop_clients(self):
        agent.mutate(self.operation())
        with patch.object(agent.ip_limiter,'online_ips',side_effect=ValueError('API unavailable')):
            result=agent.snapshot()
        self.assertTrue(result['statistics_error']); self.assertIsNone(result['traffic'])
        self.assertEqual(len(result['clients']),1)

    def test_failed_update_does_not_record_an_operation_as_applied(self):
        payload=self.operation()
        self.run.side_effect=[SimpleNamespace(stdout='active',returncode=0),subprocess.CalledProcessError(1,'xray')]
        with self.assertRaises(subprocess.CalledProcessError): agent.mutate(payload)
        registry=json.loads(m.REGISTRY.read_text())
        self.assertEqual(registry['clients'],[])
        self.assertNotIn(payload['operation_id'],registry.get('admin_operations',{}))


if __name__=='__main__': unittest.main()
