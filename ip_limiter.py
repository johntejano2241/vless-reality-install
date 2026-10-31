#!/usr/bin/python3
"""Admit a bounded number of source IPs per VLESS identity via private Unix sockets."""
from http.server import BaseHTTPRequestHandler
import ipaddress
import json
import os
from pathlib import Path
import pwd
import queue
import socket
import socketserver
import struct
import subprocess
import sys
import threading
import time

import realityctl as manager

STATE = Path('/run/reality-vless-limits/slots.json')
POLL_SECONDS = 5
IDLE_GRACE_SECONDS = 30
MAX_EVENT_BYTES = 8192
EVENTS = queue.Queue(maxsize=512)


def normalize_ip(value):
    parsed = ipaddress.ip_address(value.strip('[]'))
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped:
        parsed = parsed.ipv4_mapped
    return str(parsed)


def source_ip(source):
    if not isinstance(source, str):
        raise ValueError('Missing source address')
    # Xray's webhook source is net.JoinHostPort(address, port).
    host, separator, port = source.rpartition(':')
    if not separator or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError('Invalid source address')
    return normalize_ip(host)


def read_state():
    if not STATE.exists():
        return {'version': 1, 'clients': {}}
    state = json.loads(STATE.read_text())
    if not isinstance(state, dict) or state.get('version') != 1 or not isinstance(state.get('clients'), dict):
        raise ValueError('Invalid IP-slot state; restart Xray and the limit service to reset runtime slots')
    for identity, addresses in state['clients'].items():
        if not isinstance(identity, str) or not isinstance(addresses, dict):
            raise ValueError('Invalid IP-slot state')
        for address, seen in addresses.items():
            normalize_ip(address)
            if type(seen) not in [int, float]:
                raise ValueError('Invalid IP-slot timestamp')
    return state


def api(*arguments, input_text=None):
    result = subprocess.run([manager.XRAY, 'api', arguments[0],
        '--server=unix://' + manager.API_SOCKET, '--timeout=3', *arguments[1:]],
        input=input_text, capture_output=True, text=True, check=True, timeout=8)
    return result.stdout


def online_ips():
    data = json.loads(api('statsonlineiplist', '-all'))
    online = {}
    for user in data.get('users', []):
        email = user.get('email', '').casefold()
        if not email:
            continue
        online[email] = {normalize_ip(item['ip']) for item in user.get('ips', [])}
    return online


def choose_slots(registry, old, online, attempts, now):
    """Keep live connections and a short idle grace; admit queued new IPs in order."""
    selected = {}
    events = {}
    for name, address in attempts:
        events.setdefault(name.casefold(), []).append(normalize_ip(address))
    moment = manager.datetime.fromtimestamp(now, manager.UTC)
    for record in registry['clients']:
        limit = record.get('device_limit', 0)
        if not limit or manager.client_status(record, moment) != 'active':
            continue
        identity = record['user']['id']
        live = online.get(record['name'].casefold(), set())
        previous = old.get('clients', {}).get(identity, {})
        kept = {}
        # Reference-counted online statistics keep long-lived streams in their slot.
        for address, seen in sorted(previous.items(), key=lambda item: (-item[1], item[0])):
            if len(kept) >= limit:
                break
            if address in live:
                kept[address] = now
            elif now - seen <= IDLE_GRACE_SECONDS:
                kept[address] = seen
        # More unknown live IPs than capacity can include a just-denied attempt.
        # Do not replace known slots or admit a new source on that ambiguous sample.
        if len(live) > limit:
            selected[identity] = kept
            continue
        # Recover live admissions if the process stopped just before writing its state.
        for address in sorted(live):
            if address in kept:
                kept[address] = now
            elif len(kept) < limit:
                kept[address] = now
        for address in events.get(record['name'].casefold(), []):
            if address in kept:
                kept[address] = now
            elif len(kept) < limit:
                kept[address] = now
        selected[identity] = kept
    return {'version': 1, 'clients': selected}


def reconcile(attempts):
    with manager.locked():
        config = json.loads(manager.CONFIG.read_text())
        registry = manager.load_registry(config)
        if config.get('api', {}).get('tag') != 'reality-control':
            raise ValueError('Managed control socket is not configured; run upgrade.sh')
        now = time.time()
        moment = manager.datetime.fromtimestamp(now, manager.UTC)
        expected = {c['user']['id'] for c in registry['clients'] if manager.client_status(c, moment) == 'active'}
        actual = {user['id'] for user in manager.users(config)}
        if actual != expected:
            # A pending expiry or interrupted registry update belongs to the expiry
            # reconciler. Keep the current guards until it updates authentication;
            # removing a guard while its UUID is still authorized would fail open.
            raise ValueError('Pending client authentication update; wait for the expiry service')
        live = online_ips()  # Fail closed: no new admissions if this query fails.
        state = choose_slots(registry, read_state(), live, attempts, now)
        routing = manager.ip_routing(config, registry, moment, state['clients'])
        # Replace all routes atomically, retaining the original destination security blocks.
        # The disk config stays fail-closed for limited clients across Xray restarts.
        api('adrules', 'stdin:', input_text=json.dumps({'routing': routing}))
        manager.atomic_json(STATE, state)


class EventHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass  # Never log destinations, payloads or client credentials.

    def do_POST(self):
        try:
            self.connection.settimeout(2)
            peer = self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            _, uid, _ = struct.unpack('3i', peer)
            if uid not in [0, pwd.getpwnam('reality-vless').pw_uid]:
                self.send_error(403)
                return
            size = int(self.headers.get('Content-Length', '0'))
            if self.path != '/' or not 0 < size <= MAX_EVENT_BYTES:
                self.send_error(400)
                return
            event = json.loads(self.rfile.read(size))
            name = manager.client_name(event.get('email', ''))
            address = source_ip(event.get('source'))
            if event.get('inboundTag') != 'reality' or event.get('outboundTag') != 'blocked':
                self.send_error(400)
                return
            try:
                EVENTS.put_nowait((name, address))
            except queue.Full:
                pass  # The denied request remains blocked; a later retry can notify again.
            self.send_response(204)
            self.end_headers()
        except (ValueError, TypeError, OSError, KeyError):
            self.send_error(400)


class EventServer(socketserver.UnixStreamServer):
    request_queue_size = 64

    def server_bind(self):
        super().server_bind()
        os.chmod(self.server_address, 0o660)


def serve():
    if os.geteuid() != 0:
        raise ValueError('Run the IP-limit service as root')
    os.umask(0o077)
    # RuntimeDirectory is private and supplied by systemd, owned by root:reality-vless.
    event_path = Path(manager.EVENT_SOCKET)
    if event_path.exists():
        event_path.unlink()
    server = EventServer(str(event_path), EventHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    pending = []
    while True:
        started = time.monotonic()
        try:
            pending.append(EVENTS.get(timeout=POLL_SECONDS))
        except queue.Empty:
            pass
        while len(pending) < 512:
            try:
                pending.append(EVENTS.get_nowait())
            except queue.Empty:
                break
        try:
            reconcile(pending)
            pending.clear()
        except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
            # Existing rules remain in effect; retry admissions without a global IP ban.
            print(f'IP-limit update failed: {type(error).__name__}; retrying', file=sys.stderr, flush=True)
            pending = pending[-512:]
        # Bound API work under a burst of valid-but-denied connection attempts.
        remaining = 0.25 - (time.monotonic() - started)
        if remaining > 0:
            time.sleep(remaining)


if __name__ == '__main__':
    try:
        serve()
    except (ValueError, OSError) as error:
        print(f'IP-limit service error: {error}', file=sys.stderr)
        sys.exit(1)
