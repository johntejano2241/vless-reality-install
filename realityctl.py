#!/usr/bin/python3
"""Root-only VLESS client management with retained, renewable expiry records."""
import argparse
import base64
import copy
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import grp
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import tempfile
from urllib.parse import urlencode, quote
import uuid

ROOT = Path('/etc/reality-vless')
CONFIG = ROOT / 'config.json'
REGISTRY = ROOT / 'clients.json'
LOCK = Path('/run/lock/realityctl.lock')
UTC = timezone.utc
PHT = timezone(timedelta(hours=8))
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
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,47}', value):
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



def utcnow():
    return datetime.now(UTC)


def timestamp(value):
    return value.astimezone(UTC).isoformat(timespec='seconds')


def parse_timestamp(value):
    if not isinstance(value, str):
        raise ValueError('Invalid expiry timestamp in client records')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Expiry timestamps must include a timezone')
    return parsed.astimezone(UTC)


def parse_days(value):
    if not re.fullmatch(r'[0-9]+', str(value).strip()):
        raise ValueError('Days must be a whole number: 0 = no expiry, 1 or more = days')
    return int(str(value).strip())


def expiry_from_days(days, now):
    days = parse_days(days)
    if days == 0:
        return None
    try:
        return timestamp(now + timedelta(days=days))
    except OverflowError as exc:
        raise ValueError('Number of days is too large') from exc


def client_status(record, now):
    expiry = record['expires_at']
    return 'expired' if expiry is not None and parse_timestamp(expiry) <= now else 'active'


def display_expiry(record):
    if record['expires_at'] is None:
        return 'Never'
    return parse_timestamp(record['expires_at']).astimezone(PHT).strftime('%Y-%m-%d %H:%M:%S +08:00')


def validate_registry(registry):
    if not isinstance(registry, dict) or registry.get('version') != 1 or not isinstance(registry.get('clients'), list):
        raise ValueError('Invalid clients.json; restore a valid backup before continuing')
    names, identities = set(), set()
    for record in registry['clients']:
        if not isinstance(record, dict):
            raise ValueError('Invalid client record')
        name = client_name(record.get('name', ''))
        user = record.get('user')
        if not isinstance(user, dict) or user.get('email') != name or not isinstance(user.get('id'), str) or not user['id']:
            raise ValueError('Invalid client identity in clients.json')
        if name in names or user['id'] in identities:
            raise ValueError('Duplicate client name or identity in clients.json')
        names.add(name)
        identities.add(user['id'])
        if 'expires_at' not in record:
            raise ValueError('Missing client expiry in clients.json')
        if record['expires_at'] is not None:
            parse_timestamp(record['expires_at'])
    return registry


def registry_from_config(config):
    # Legacy accounts have no expiry; preserve every existing UUID and user option.
    return validate_registry({'version': 1, 'clients': [
        {'name': user['email'], 'user': copy.deepcopy(user), 'expires_at': None}
        for user in users(config)]})


def load_registry(config):
    if REGISTRY.exists():
        return validate_registry(json.loads(REGISTRY.read_text()))
    registry = registry_from_config(config)
    atomic_json(REGISTRY, registry)
    return registry


def find_client(registry, name):
    client_name(name)
    exact = [c for c in registry['clients'] if c['name'] == name]
    matches = exact or [c for c in registry['clients'] if c['name'].casefold() == name.casefold()]
    if not matches:
        raise ValueError(f"Client '{name}' not found")
    if len(matches) > 1:
        raise ValueError('Ambiguous client name; use its exact capitalization')
    return matches[0]


def edit_clients(registry, action, name, days, now):
    client_name(name)
    updated = copy.deepcopy(registry)
    if action == 'add':
        if any(c['name'].casefold() == name.casefold() for c in updated['clients']):
            raise ValueError(f"Client '{name}' already exists; renew it if expired")
        updated['clients'].append({'name': name,
            'user': {'id': str(uuid.uuid4()), 'email': name, 'flow': 'xtls-rprx-vision'},
            'expires_at': expiry_from_days(days, now)})
    elif action == 'renew':
        record = find_client(updated, name)
        if client_status(record, now) != 'expired':
            raise ValueError(f"Client '{record['name']}' is active; only expired clients can be renewed")
        record['expires_at'] = expiry_from_days(days, now)
    elif action == 'remove':
        updated['clients'].remove(find_client(updated, name))
    else:
        raise ValueError('Unknown client action')
    return validate_registry(updated)


def render_config(config, registry, now):
    validate_registry(registry)
    rendered = copy.deepcopy(config)
    rendered['inbounds'][0]['settings']['clients'] = [
        copy.deepcopy(c['user']) for c in registry['clients'] if client_status(c, now) == 'active']
    return rendered


def share_link(config, meta, record):
    inbound = config['inbounds'][0]
    reality = inbound['streamSettings']['realitySettings']
    query = urlencode({'encryption': 'none', 'security': 'reality', 'sni': reality['serverNames'][0],
        'fp': 'chrome', 'pbk': meta['publicKey'], 'sid': reality['shortIds'][0],
        'type': 'tcp', 'flow': 'xtls-rprx-vision'})
    return f"vless://{record['user']['id']}@{meta['endpoint']}:{inbound['port']}?{query}#{quote(record['name'])}"


def restart_service():
    subprocess.run(['systemctl', 'restart', SERVICE], check=True, timeout=45)
    subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE], check=True, timeout=10)


def commit(config, registry=None, restart=True):
    """Validate first; publish registry before runtime config so the timer can recover a crash.

    All callers hold LOCK. An ordinary validation/restart failure restores both
    files. A crash between atomic replacements leaves a complete desired registry;
    the next expiry sweep regenerates the runtime config from it.
    """
    candidate = ROOT / 'candidate.json'
    old_config = json.loads(CONFIG.read_text()) if CONFIG.exists() else None
    old_registry = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else None
    changed_config = config != old_config
    changed_registry = registry is not None and registry != old_registry
    if not changed_config and not changed_registry:
        return False
    try:
        if changed_config:
            atomic_json(candidate, config, True)
            subprocess.run([XRAY, 'run', '-test', '-config', str(candidate)], check=True,
                           stdout=subprocess.DEVNULL, timeout=30)
        try:
            if changed_registry:
                atomic_json(REGISTRY, registry)
            if changed_config:
                os.replace(candidate, CONFIG)
                if restart:
                    restart_service()
        except (OSError, subprocess.SubprocessError) as exc:
            if changed_registry:
                if old_registry is None:
                    REGISTRY.unlink(missing_ok=True)
                else:
                    atomic_json(REGISTRY, old_registry)
            if changed_config:
                if old_config is None:
                    CONFIG.unlink(missing_ok=True)
                else:
                    atomic_json(CONFIG, old_config, True)
                if restart and old_config is not None:
                    try:
                        restart_service()
                    except (OSError, subprocess.SubprocessError) as recovery_error:
                        raise RuntimeError('Previous files restored, but service recovery failed; check journalctl') from recovery_error
            raise RuntimeError('Update failed; previous client records and configuration restored') from exc
    finally:
        candidate.unlink(missing_ok=True)
    return changed_config and restart


@contextmanager
def locked():
    # /run/lock may be shared. Never follow a symlink or truncate a lock target.
    fd = os.open(LOCK, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+') as lock:
        info = os.fstat(lock.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError('Management lock must be a regular file owned by root')
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def print_table(records, now):
    print('Expiration dates: Philippine time (UTC+08:00)')
    rows = [(c['name'], client_status(c, now), display_expiry(c)) for c in records]
    widths = [max([len(row[i]) for row in rows] + [len(title)])
              for i, title in enumerate(['Name', 'Status', 'Expiration date'])]
    fmt = '  '.join('{:<%d}' % width for width in widths)
    print(fmt.format('Name', 'Status', 'Expiration date'))
    for row in rows:
        print(fmt.format(*row))
    if not rows:
        print('(no clients)')


def execute(command, name=None, days=None):
    with locked():
        config = json.loads(CONFIG.read_text())
        registry = load_registry(config)
        now = utcnow()
        if command == 'migrate':
            print(f"Client records ready: {len(registry['clients'])}. Existing identities preserved.")
            return
        if command in ['add', 'renew', 'remove']:
            registry = edit_clients(registry, command, name, days, now)
        # Reads and the timer also enforce due expirations; expired records stay in clients.json.
        active_config = render_config(config, registry, now)
        restarted = commit(active_config, registry)
        if command in ['add', 'renew']:
            record = find_client(registry, name)
            print_table([record], now)
            print(share_link(active_config, json.loads((ROOT / 'server.json').read_text()), record))
        elif command == 'remove':
            print(f"Removed client '{name}' permanently.")
        elif command == 'find':
            record = find_client(registry, name)
            print_table([record], now)
            if client_status(record, now) == 'expired':
                print('Access is disabled until this client is renewed. Its connection link is retained.')
            print(share_link(active_config, json.loads((ROOT / 'server.json').read_text()), record))
        elif command == 'list':
            print_table(sorted(registry['clients'], key=lambda c: c['name'].casefold()), now)
        if restarted:
            print('Access list updated; service restarted. Other clients may briefly reconnect.')


def prompt_days():
    return parse_days(input('Expiration days (0 = no expiry, 1 or more = days): ').strip())


def menu():
    # Never hold the management lock while waiting for input: the timer must keep running.
    options = {'1': 'add', '2': 'renew', '3': 'find', '4': 'list', '5': 'remove'}
    while True:
        print('\nVLESS + REALITY client manager\n1. Add client\n2. Renew expired client'
              '\n3. Find client\n4. Show all clients\n5. Remove client\n0. Exit')
        try:
            choice = input('Choose an option: ').strip()
            if choice == '0':
                return
            if choice not in options:
                print('Error: choose a menu option from 0 to 5.')
                continue
            command = options[choice]
            name = input('Client name: ').strip() if command != 'list' else None
            if name is not None:
                client_name(name)
            days = prompt_days() if command in ['add', 'renew'] else None
            if command == 'remove' and input(f"Permanently remove '{name}'? [y/N]: ").strip().lower() != 'y':
                print('Removal cancelled.')
                continue
            execute(command, name, days)
        except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
            print(f'Error: {error}', file=sys.stderr)
        except (EOFError, KeyboardInterrupt):
            print('\nExiting.')
            return


def main(argv=None):
    parser = argparse.ArgumentParser(description='Manage VLESS + REALITY clients and expiry (root required)')
    sub = parser.add_subparsers(dest='command')
    for action in ['add', 'renew']:
        child = sub.add_parser(action)
        child.add_argument('name')
        child.add_argument('--days', help='0 = no expiry, 1 or more = days; prompted if omitted')
    sub.add_parser('remove', aliases=['revoke']).add_argument('name')
    sub.add_parser('find', aliases=['show']).add_argument('name')
    sub.add_parser('list', aliases=['all'])
    for action in ['menu', 'status', 'expire', 'migrate']:
        sub.add_parser(action)
    for action in ['init', 'check-input']:
        child = sub.add_parser(action)
        child.add_argument('endpoint')
        child.add_argument('sni')
        if action == 'init':
            child.add_argument('port', type=int)
    args = parser.parse_args(argv)
    if args.command == 'check-input':
        endpoint(args.endpoint)
        hostname(args.sni)
        return
    if os.geteuid() != 0:
        raise ValueError('Run with sudo')
    os.umask(0o077)
    command = {'show': 'find', 'revoke': 'remove', 'all': 'list'}.get(args.command, args.command)
    if command in [None, 'menu']:
        menu()
        return
    if command == 'status':
        subprocess.run(['systemctl', 'status', '--no-pager', SERVICE], check=True)
        return
    if command == 'init':
        endpoint(args.endpoint)
        hostname(args.sni)
        if not 1 <= args.port <= 65535:
            raise ValueError('Invalid port')
        with locked():
            if any(p.exists() for p in [CONFIG, REGISTRY, ROOT / 'server.json']):
                raise ValueError('Already initialized; refusing to overwrite keys')
            private, public = keypair()
            config = make_config(args.sni, args.port, private)
            config['inbounds'][0]['streamSettings']['realitySettings']['shortIds'] = [secrets.token_hex(8)]
            commit(config, {'version': 1, 'clients': []}, restart=False)
            atomic_json(ROOT / 'server.json', {'endpoint': args.endpoint, 'publicKey': public})
        return
    name = getattr(args, 'name', None)
    if name is not None:
        client_name(name)
    days = None
    if command in ['add', 'renew']:
        if args.days is not None:
            days = parse_days(args.days)
        elif sys.stdin.isatty():
            days = prompt_days()
        else:
            raise ValueError('Supply --days 0 for no expiry or --days N for a number of days')
    execute(command, name, days)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError, EOFError) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print('\nExiting.', file=sys.stderr)
        sys.exit(130)
