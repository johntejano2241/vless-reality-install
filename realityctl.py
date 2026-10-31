#!/usr/bin/python3
"""Root-only client management; config is the sole source of truth."""
import argparse
import base64
import copy
import fcntl
import grp
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
from urllib.parse import urlencode, quote
import uuid

ROOT = Path('/etc/reality-vless')
CONFIG = ROOT / 'config.json'
XRAY = '/usr/local/bin/xray-reality'
SERVICE = 'reality-vless'


def hostname(value):
    if len(value) > 253 or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', value):
        raise ValueError('Invalid hostname')
    if any(not label or len(label) > 63 or label.startswith('-') or label.endswith('-') for label in value.split('.')):
        raise ValueError('Invalid hostname labels')
    return value


def endpoint(value):
    try:
        address = ipaddress.ip_address(value)
        if address.version != 4:
            raise ValueError('Only IPv4 server endpoints are supported')
        return str(address)
    except ValueError:
        return hostname(value)


def client_name(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,47}', value):
        raise ValueError('Client name: 1–48 letters, digits, underscores or hyphens')
    return value


def keypair():
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption
    key = X25519PrivateKey.generate()
    encode = lambda data: base64.urlsafe_b64encode(data).decode().rstrip('=')
    return (encode(key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())),
            encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)))


def make_config(sni, port, private):
    return {
        'log': {'loglevel': 'warning'},
        'inbounds': [{'tag': 'reality', 'listen': '0.0.0.0', 'port': port,
            'protocol': 'vless', 'settings': {'clients': [], 'decryption': 'none'},
            'streamSettings': {'network': 'tcp', 'security': 'reality',
                'realitySettings': {'show': False, 'target': f'{sni}:443',
                    'xver': 0, 'serverNames': [sni], 'privateKey': private, 'shortIds': []}}}],
        'outbounds': [{'tag': 'direct', 'protocol': 'freedom'}, {'tag': 'blocked', 'protocol': 'blackhole'}],
        'routing': {'domainStrategy': 'IPOnDemand', 'rules': [
            {'type': 'field', 'ip': ['0.0.0.0/8', '10.0.0.0/8', '100.64.0.0/10', '127.0.0.0/8',
                '169.254.0.0/16', '172.16.0.0/12', '192.168.0.0/16', '224.0.0.0/4',
                '240.0.0.0/4', '::/128', '::1/128', 'fc00::/7', 'fe80::/10', 'ff00::/8'],
             'outboundTag': 'blocked'}]}}


def users(config):
    return config['inbounds'][0]['settings']['clients']


def change(config, action, name):
    client_name(name)
    matches = [c for c in users(config) if c['email'] == name]
    if action == 'add':
        if matches:
            raise ValueError('Client already exists')
        users(config).append({'id': str(uuid.uuid4()), 'email': name, 'flow': 'xtls-rprx-vision'})
    else:
        if not matches:
            raise ValueError('Client not found')
        users(config).remove(matches[0])
    return config


def share_link(config, meta, name):
    client = next((c for c in users(config) if c['email'] == name), None)
    if client is None:
        raise ValueError('Client not found')
    inbound = config['inbounds'][0]
    reality = inbound['streamSettings']['realitySettings']
    host = meta['endpoint']
    if ':' in host:
        host = f'[{host}]'
    query = urlencode({'encryption': 'none', 'security': 'reality', 'sni': reality['serverNames'][0],
        'fp': 'chrome', 'pbk': meta['publicKey'], 'sid': reality['shortIds'][0],
        'type': 'tcp', 'flow': 'xtls-rprx-vision'})
    return f"vless://{client['id']}@{host}:{inbound['port']}?{query}#{quote(name)}"


def atomic_json(path, data, service_readable=False):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
            if service_readable:
                os.fchown(stream.fileno(), 0, grp.getgrnam('reality-vless').gr_gid)
                os.fchmod(stream.fileno(), 0o640)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def commit(config, restart=True):
    candidate = ROOT / 'candidate.json'
    old = json.loads(CONFIG.read_text()) if CONFIG.exists() else None
    try:
        atomic_json(candidate, config, True)
        subprocess.run([XRAY, 'run', '-test', '-config', str(candidate)], check=True,
                       stdout=subprocess.DEVNULL)
        os.replace(candidate, CONFIG)
        if restart:
            try:
                subprocess.run(['systemctl', 'restart', SERVICE], check=True)
                subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE], check=True)
            except subprocess.CalledProcessError:
                if old is not None:
                    atomic_json(CONFIG, old, True)
                    subprocess.run(['systemctl', 'restart', SERVICE], check=False)
                raise RuntimeError('Service restart failed; previous config restored. Check journalctl.')
    finally:
        candidate.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description='Manage VLESS + REALITY clients (root required)')
    sub = parser.add_subparsers(dest='command', required=True)
    for action in ['add', 'revoke', 'show']:
        sub.add_parser(action).add_argument('name')
    sub.add_parser('list')
    sub.add_parser('status')
    for action in ['init', 'check-input']:
        child = sub.add_parser(action)
        child.add_argument('endpoint')
        child.add_argument('sni')
        if action == 'init':
            child.add_argument('port', type=int)
    args = parser.parse_args()
    if args.command == 'check-input':
        endpoint(args.endpoint)
        hostname(args.sni)
        return
    if os.geteuid() != 0:
        raise ValueError('Run with sudo')
    os.umask(0o077)
    with open('/run/lock/realityctl.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.command == 'init':
            endpoint(args.endpoint)
            hostname(args.sni)
            if not 1 <= args.port <= 65535:
                raise ValueError('Invalid port')
            if CONFIG.exists() or (ROOT / 'server.json').exists():
                raise ValueError('Already initialized; refusing to overwrite keys')
            private, public = keypair()
            config = make_config(args.sni, args.port, private)
            config['inbounds'][0]['streamSettings']['realitySettings']['shortIds'] = [secrets.token_hex(8)]
            commit(config, restart=False)
            atomic_json(ROOT / 'server.json', {'endpoint': args.endpoint, 'publicKey': public})
            return
        if args.command == 'status':
            subprocess.run(['systemctl', 'status', '--no-pager', SERVICE], check=True)
            return
        config = json.loads(CONFIG.read_text())
        if args.command == 'list':
            print('\n'.join(c['email'] for c in users(config)) or '(no clients)')
            return
        client_name(args.name)
        if args.command in ['add', 'revoke']:
            commit(change(copy.deepcopy(config), args.command, args.name))
            config = json.loads(CONFIG.read_text())
            print(f'{args.command}: {args.name}. Service restarted; existing connections were interrupted.')
        if args.command in ['add', 'show']:
            print(share_link(config, json.loads((ROOT / 'server.json').read_text()), args.name))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)
