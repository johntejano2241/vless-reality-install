#!/usr/bin/python3
"""Narrow local admin bridge. Only an OS-authorized peer can use its Unix socket."""
import argparse
import contextlib
import hashlib
from http.server import BaseHTTPRequestHandler
import io
import json
import os
from pathlib import Path
import pwd
import secrets
import socket
import socketserver
import sqlite3
import struct
import subprocess
import tarfile
import time
import uuid

import ip_limiter
import realityctl as manager

SOCKET = Path('/run/reality-vless-admin/agent.sock')
BACKUPS = Path('/var/backups/reality-vless-admin')
BACKUP_KEY = Path('/etc/reality-vless-admin/backup.key')
WEB_DATA = Path('/var/lib/reality-vless-admin')
WEB_ENV = Path('/etc/reality-vless-admin/app.env')
MAX_BODY = 8192


def version(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def public_record(record, now):
    return {'name': record['name'], 'status': manager.client_status(record, now),
            'expires_at': record['expires_at'], 'ip_limit': record.get('device_limit', 0),
            'version': version(record)}


def mutate(payload):
    allowed = {'operation_id', 'action', 'name', 'days', 'devices', 'expected_version'}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise ValueError('Invalid operation fields')
    operation = str(uuid.UUID(payload['operation_id']))
    action = payload['action']
    if action not in ['add', 'extend', 'suspend', 'resume', 'rotate', 'set-limit', 'remove']:
        raise ValueError('Unsupported operation')
    name = manager.client_name(payload['name'])
    days = manager.parse_days(payload.get('days', 0))
    devices = manager.parse_devices(payload.get('devices', 0))
    if days > 36500 or devices > 1000:
        raise ValueError('Limit outside supported range')
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    with manager.locked():
        config = json.loads(manager.CONFIG.read_text())
        registry = manager.load_registry(config)
        history = registry.get('admin_operations', {})
        if not isinstance(history, dict):
            raise ValueError('Invalid operation history')
        if operation in history:
            if history[operation]['digest'] != digest:
                raise ValueError('Operation ID already used for another request')
            return history[operation]['result']
        now = manager.utcnow()
        if action != 'add':
            record = manager.find_client(registry, name)
            if not secrets.compare_digest(str(payload.get('expected_version', '')), version(record)):
                raise ValueError('Client changed; refresh before retrying')
        if action in ['add', 'set-limit'] and devices:
            manager.require_ip_control(config)
        updated = manager.edit_clients(registry, action, name, days, now, devices=devices)
        result = {'name': name, 'removed': True} if action == 'remove' else public_record(manager.find_client(updated, name), now)
        updated.setdefault('admin_operations', {})[operation] = {'digest': digest, 'result': result}
        # Keep tombstones: forgotten operation IDs must never grant access again.
        # The SQLite/web queue holds UUIDs, but the root registry owns the applied history.
        active = manager.render_config(config, updated, now)
        manager.commit(active, updated, force_restart=action in ['set-limit', 'rotate'])
        return result


def snapshot():
    with manager.locked():
        config = json.loads(manager.CONFIG.read_text())
        registry = manager.load_registry(config)
        clients = [public_record(record, manager.utcnow()) for record in registry['clients']]
    services = {}
    for unit in [manager.SERVICE, manager.IP_SERVICE, 'reality-vless-expire.timer']:
        check = subprocess.run(['systemctl', 'is-active', unit], capture_output=True, text=True, timeout=8)
        services[unit] = check.stdout.strip() or 'unknown'
    invocation = subprocess.run(['systemctl', 'show', manager.SERVICE, '-p', 'InvocationID', '--value'],
                                capture_output=True, text=True, check=True, timeout=8).stdout.strip()
    data = {'clients': clients, 'services': services, 'observed_at': manager.timestamp(manager.utcnow()),
            'epoch': invocation, 'online_ips': None, 'traffic': None, 'statistics_error': False}
    try:
        data['online_ips'] = {key: sorted(value) for key, value in ip_limiter.online_ips().items()}
        counters = json.loads(ip_limiter.api('statsquery', '-pattern=user>>>'))
        traffic = {}
        for counter in counters.get('stat', []):
            parts = counter.get('name', '').split('>>>')
            if len(parts) == 4 and parts[0] == 'user' and parts[2] == 'traffic' and parts[3] in ['uplink', 'downlink']:
                traffic.setdefault(parts[1], {})[parts[3]] = max(0, int(counter['value']))
        data['traffic'] = traffic
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        data['statistics_error'] = True
    return data


def reveal(name, expected_version):
    with manager.locked():
        config = json.loads(manager.CONFIG.read_text())
        record = manager.find_client(manager.load_registry(config), manager.client_name(name))
        if not secrets.compare_digest(str(expected_version), version(record)):
            raise ValueError('Client changed; refresh before revealing its link')
        return {'link': manager.share_link(config, json.loads((manager.ROOT / 'server.json').read_text()), record)}


def backup():
    from cryptography.fernet import Fernet
    BACKUPS.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not BACKUP_KEY.exists():
        fd = os.open(BACKUP_KEY, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(Fernet.generate_key())
    raw = io.BytesIO()
    with manager.locked(), tarfile.open(fileobj=raw, mode='w:gz') as archive:
        for filename in ['config.json', 'clients.json', 'server.json']:
            archive.add(manager.ROOT / filename, arcname=filename, recursive=False)
        if WEB_ENV.exists():
            archive.add(WEB_ENV, arcname='web-app.env', recursive=False)
        database = WEB_DATA / 'database' / 'database.sqlite'
        if database.exists():
            with contextlib.closing(sqlite3.connect(database)) as source, contextlib.closing(sqlite3.connect(':memory:')) as copy:
                source.backup(copy)
                sql = '\n'.join(copy.iterdump()).encode()
            info = tarfile.TarInfo('dashboard.sql')
            info.size = len(sql)
            archive.addfile(info, io.BytesIO(sql))
    target = BACKUPS / (time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + secrets.token_hex(4) + '.fernet')
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(Fernet(BACKUP_KEY.read_bytes()).encrypt(raw.getvalue()))
    return {'file': target.name, 'created_at': manager.timestamp(manager.utcnow())}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        self.handle_request(False)

    def do_POST(self):
        self.handle_request(True)

    def handle_request(self, post):
        try:
            self.connection.settimeout(70)
            _, uid, _ = struct.unpack('3i', self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid not in [0, pwd.getpwnam('reality-admin').pw_uid]:
                return self.respond(403, {'error': 'Unauthorized local peer'})
            size = int(self.headers.get('Content-Length', '0'))
            if size < 0 or size > MAX_BODY or (post and size == 0):
                return self.respond(400, {'error': 'Invalid request size'})
            payload = json.loads(self.rfile.read(size)) if post else {}
            if not post and self.path == '/v1/snapshot':
                return self.respond(200, snapshot())
            if not post and self.path == '/v1/backups':
                return self.respond(200, {'files': sorted(path.name for path in BACKUPS.glob('*.fernet'))[-30:]})
            if post and self.path == '/v1/commands':
                return self.respond(200, mutate(payload))
            if post and self.path == '/v1/link' and set(payload) == {'name', 'expected_version'}:
                return self.respond(200, reveal(payload['name'], payload['expected_version']))
            return self.respond(404, {'error': 'Unknown endpoint'})
        except (ValueError, TypeError, KeyError):
            return self.respond(409, {'error': 'Invalid or stale operation; refresh and retry'})
        except (OSError, RuntimeError, subprocess.SubprocessError):
            return self.respond(503, {'error': 'VPN manager unavailable; inspect its service journal'})

    def respond(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)


def main():
    if os.geteuid() != 0:
        raise ValueError('Run as root')
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['serve', 'backup'])
    args = parser.parse_args()
    if args.command == 'backup':
        print(json.dumps(backup()))
        return
    SOCKET.unlink(missing_ok=True)
    with socketserver.UnixStreamServer(str(SOCKET), Handler) as server:
        os.chmod(SOCKET, 0o660)
        os.chown(SOCKET, 0, pwd.getpwnam('reality-admin').pw_gid)
        server.serve_forever()


if __name__ == '__main__':
    main()
