"""CI-only end-to-end test: real REALITY clients from distinct source addresses."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import threading
import time

XRAY = '/usr/local/bin/xray-reality'
SERVER_IP = '198.19.0.1'
SOURCE1, SOURCE2 = '198.19.0.2', '198.19.0.3'
TARGET_IP = '198.19.0.10'
MARKER = b'IP_SLOT_TEST_OK'
STOP = threading.Event()
HITS = []
LAST_CURL = None


def command(*args, **kwargs):
    try:
        return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs)
    except subprocess.CalledProcessError as error:
        print('Command failed:', ' '.join(args), flush=True)
        print(error.stderr or '', flush=True)
        raise


def wait_for(predicate, timeout, message):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.5)
    raise AssertionError(message)


class Target(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        HITS.append(self.path)
        self.send_response(200)
        if self.path != '/hold':
            self.send_header('Content-Length', str(len(MARKER) + 1))
        self.end_headers()
        try:
            self.wfile.write(MARKER + b'\n')
            self.wfile.flush()
            if self.path == '/hold':
                while not STOP.wait(0.5):
                    self.wfile.write(b'.')
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ssl.SSLEOFError):
            pass


def curl_args(port, path='/', maximum='5'):
    return ['curl', '--silent', '--show-error', '--no-buffer', '--insecure', '--noproxy', '',
            '--proxy', f'socks5h://127.0.0.1:{port}', '--connect-timeout', '3',
            '--max-time', maximum, f'https://{TARGET_IP}:18080{path}']


def fetch(port):
    global LAST_CURL
    result = subprocess.run(curl_args(port), capture_output=True, timeout=8)
    LAST_CURL = (port, result.returncode, result.stdout[:300], result.stderr[:500])
    return result.returncode == 0 and MARKER in result.stdout


def main():
    if os.geteuid() != 0 or os.environ.get('GITHUB_ACTIONS') != 'true':
        raise ValueError('Run only as root on a disposable GitHub Actions runner')
    os.umask(0o077)
    processes, aliases, handles = [], [], []
    httpd = None
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        try:
            for address in [SERVER_IP, SOURCE1, SOURCE2, TARGET_IP]:
                command('ip', 'address', 'add', address + '/32', 'dev', 'lo')
                aliases.append(address)
            httpd = ThreadingHTTPServer((TARGET_IP, 18080), Target)
            cert, key = root / 'target.crt', root / 'target.key'
            command('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                '-subj', '/CN=local-ip-slot-test', '-keyout', str(key), '-out', str(cert))
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_3
            context.load_cert_chain(cert, key)
            httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            direct = command('curl', '--silent', '--show-error', '--insecure', '--noproxy', '*', '--max-time', '3', f'https://{TARGET_IP}:18080/')
            assert MARKER.decode() in direct.stdout, 'The local HTTP fixture is unavailable'
            command('realityctl', 'add', 'slot-limited', '--days', '0', '--devices', '1')
            command('realityctl', 'add', 'slot-unlimited', '--days', '0', '--devices', '0')
            config = json.loads(Path('/etc/reality-vless/config.json').read_text())
            config['log']['loglevel'] = 'info'
            # Xray's default freedom policy blocks reserved destinations even
            # after routing allows them. Permit only this disposable local TLS
            # fixture; production configs keep the default destination policy.
            direct_outbound = next(outbound for outbound in config['outbounds'] if outbound.get('tag') == 'direct')
            direct_outbound.setdefault('settings', {})['finalRules'] = [
                {'action': 'allow', 'network': 'tcp', 'ip': [TARGET_IP + '/32'], 'port': '18080'}]
            Path('/etc/reality-vless/config.json').write_text(json.dumps(config))
            command('systemctl', 'reset-failed', 'reality-vless', 'reality-vless-limits')
            command('systemctl', 'restart', 'reality-vless')
            meta = json.loads(Path('/etc/reality-vless/server.json').read_text())
            records = json.loads(Path('/etc/reality-vless/clients.json').read_text())['clients']
            users = {record['name']: record['user']['id'] for record in records}
            reality = config['inbounds'][0]['streamSettings']['realitySettings']
            # Uses the real configured TLS target for REALITY camouflage. HTTP test
            # payloads stay on local benchmark addresses, with no public website dependency.
            for index, (name, source) in enumerate([
                ('slot-limited', SOURCE1), ('slot-limited', SOURCE2),
                ('slot-unlimited', SOURCE2), ('slot-limited', SOURCE1)]):
                port = 19081 + index
                client = {'log': {'loglevel': 'info'},
                    'inbounds': [{'listen': '127.0.0.1', 'port': port, 'protocol': 'socks', 'settings': {'udp': False}}],
                    'outbounds': [{'protocol': 'vless', 'sendThrough': source,
                        'settings': {'vnext': [{'address': SERVER_IP, 'port': config['inbounds'][0]['port'],
                            'users': [{'id': users[name], 'encryption': 'none', 'flow': 'xtls-rprx-vision'}]}]},
                        'streamSettings': {'network': 'tcp', 'security': 'reality',
                            'realitySettings': {'serverName': reality['serverNames'][0],
                                'password': meta['publicKey'], 'shortId': reality['shortIds'][0], 'fingerprint': 'chrome'}}}]}
                path = root / f'client-{index}.json'
                path.write_text(json.dumps(client))
                log = (root / f'client-{index}.log').open('wb')
                handles.append(log)
                processes.append(subprocess.Popen([XRAY, 'run', '-config', str(path)], stdout=log, stderr=log))
            time.sleep(1)
            invocation = command('systemctl', 'show', 'reality-vless', '-p', 'InvocationID', '--value').stdout
            wait_for(lambda: fetch(19083), 20, 'The unlimited control account cannot reach the HTTPS fixture')
            wait_for(lambda: fetch(19081), 40, 'First source IP was not admitted')
            hold_output = (root / 'hold-output').open('wb')
            handles.append(hold_output)
            hold = subprocess.Popen(curl_args(19081, '/hold', '120'), stdout=hold_output, stderr=subprocess.DEVNULL)
            processes.append(hold)
            wait_for(lambda: MARKER in (root / 'hold-output').read_bytes(), 15, 'Could not establish the persistent first-IP stream')
            # A second process behind the SAME source address still uses one IP slot.
            assert fetch(19084), 'Two devices using one source IP should share a slot'
            for _ in range(3):
                assert not fetch(19082), 'A second distinct IP bypassed the one-slot limit'
                assert hold.poll() is None, 'Limit enforcement interrupted the admitted stream'
            assert fetch(19083), 'An unrelated unlimited account was blocked on the same source IP'
            after = command('systemctl', 'show', 'reality-vless', '-p', 'InvocationID', '--value').stdout
            assert after == invocation, 'Admitting or denying IPs should not restart Xray'
            # Once the first IP disconnects and the 30-second idle grace elapses,
            # the second source can take the free slot without a new connection link.
            hold.terminate()
            hold.wait(timeout=5)
            wait_for(lambda: fetch(19082), 55, 'The disconnected IP slot was not released')
            assert fetch(19083), 'The unlimited account stopped working after slot replacement'
            print('Real REALITY clients: first-IP admission, same-IP sharing, excess-IP denial,')
            print('per-account isolation, uninterrupted streams and idle-slot reuse passed.')
        except Exception:
            print('Target requests:', HITS, 'Last curl:', LAST_CURL, flush=True)
            for log_path in sorted(root.glob('client-*.log')):
                print(log_path.name, log_path.read_text(errors='replace')[-1600:], flush=True)
            # CI fixtures only: preserve useful diagnostics before cleanup restarts services.
            for args in [
                ['journalctl', '-u', 'reality-vless-limits', '--no-pager', '-n', '80'],
                ['journalctl', '-u', 'reality-vless', '--no-pager', '-n', '80'],
                [XRAY, 'api', 'statsonlineiplist', '--server=unix:///run/reality-vless-api/control.sock', '-all'],
                ['systemctl', 'show', 'reality-vless-limits', '-p', 'ActiveState', '-p', 'ExecMainStatus']]:
                result = subprocess.run(args, capture_output=True, text=True)
                print(result.stdout, result.stderr, flush=True)
            state = Path('/run/reality-vless-limits/slots.json')
            print('Runtime slot state:', state.read_text() if state.exists() else '(missing)', flush=True)
            raise
        finally:
            STOP.set()
            for process in processes:
                if process.poll() is None:
                    process.terminate()
            for process in processes:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            for handle in handles:
                handle.close()
            if httpd:
                httpd.shutdown()
                httpd.server_close()
            for name in ['slot-limited', 'slot-unlimited']:
                subprocess.run(['realityctl', 'remove', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for address in aliases:
                subprocess.run(['ip', 'address', 'del', address + '/32', 'dev', 'lo'], check=False)


if __name__ == '__main__':
    main()
