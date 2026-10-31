#!/usr/bin/env bash
# CI-only: builds a legacy installation on a disposable Ubuntu runner.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 && ${GITHUB_ACTIONS:-false} == true ]] || { echo 'Run only as root on a disposable GitHub Actions runner.' >&2; exit 1; }
binary=${1:?Pass the verified Xray binary path}
base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
[[ ! -e /etc/reality-vless ]] || { echo 'Refusing to overwrite an existing installation.' >&2; exit 1; }
useradd --system --user-group --no-create-home --shell /usr/sbin/nologin reality-vless
install -d -m 750 -o root -g reality-vless /etc/reality-vless
install -d -m 755 /usr/local/lib/reality-vless
install -m 755 "$binary" /usr/local/bin/xray-reality
# The legacy registry lived only in config.json. The installed manager is replaced
# by upgrade.sh; its content is a placeholder so a failed migration is detectable.
printf '#!/usr/bin/python3\nprint("legacy manager")\n' > /usr/local/lib/reality-vless/realityctl.py
chmod 755 /usr/local/lib/reality-vless/realityctl.py
ln -s /usr/local/lib/reality-vless/realityctl.py /usr/local/bin/realityctl
/usr/bin/python3 - "$base" <<'PY'
import importlib.util, json, pathlib, sys, uuid, grp, os
spec = importlib.util.spec_from_file_location('m', pathlib.Path(sys.argv[1]) / 'realityctl.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
private, public = m.keypair()
config = m.make_config('www.microsoft.com', 18443, private)
config['inbounds'][0]['streamSettings']['realitySettings']['shortIds'] = ['0123456789abcdef']
config['inbounds'][0]['settings']['clients'] = [{'id': str(uuid.uuid4()), 'email': 'andrea', 'flow': 'xtls-rprx-vision'}]
root = pathlib.Path('/etc/reality-vless')
(root / 'config.json').write_text(json.dumps(config))
os.chown(root / 'config.json', 0, grp.getgrnam('reality-vless').gr_gid)
os.chmod(root / 'config.json', 0o640)
(root / 'server.json').write_text(json.dumps({'endpoint': '203.0.113.1', 'publicKey': public}))
pathlib.Path('/tmp/reality-legacy-config.json').write_text(json.dumps(config))
PY
meta_hash=$(sha256sum /etc/reality-vless/server.json)
binary_hash=$(sha256sum /usr/local/bin/xray-reality)
cat > /etc/systemd/system/reality-vless.service <<'UNIT'
[Unit]
Description=Disposable legacy VLESS test installation
After=network.target
[Service]
User=reality-vless
Group=reality-vless
ExecStart=/usr/local/bin/xray-reality run -config /etc/reality-vless/config.json
Restart=on-failure
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl start reality-vless
bash "$base/upgrade.sh"
[[ $meta_hash == "$(sha256sum /etc/reality-vless/server.json)" ]]
[[ $binary_hash == "$(sha256sum /usr/local/bin/xray-reality)" ]]
/usr/bin/python3 - <<'PY'
import json, pathlib
root = pathlib.Path('/etc/reality-vless')
legacy = json.loads(pathlib.Path('/tmp/reality-legacy-config.json').read_text())
current = json.loads((root / 'config.json').read_text())
records = json.loads((root / 'clients.json').read_text())['clients']
assert current == legacy
assert len(records) == 1 and records[0]['expires_at'] is None
assert records[0]['user'] == legacy['inbounds'][0]['settings']['clients'][0]
PY
# Re-running the upgrade is idempotent and preserves existing records.
bash "$base/upgrade.sh"
realityctl add test-phone --days 1 >/dev/null
realityctl show test-phone > /tmp/reality-test-phone-before.txt
/usr/bin/python3 - <<'PY'
import datetime, json, pathlib
p = pathlib.Path('/etc/reality-vless/clients.json')
registry = json.loads(p.read_text())
for c in registry['clients']:
    if c['name'] == 'test-phone':
        c['expires_at'] = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=5)).isoformat()
p.write_text(json.dumps(registry))
PY
systemctl start reality-vless-expire.service
realityctl list > /tmp/reality-list.txt
/usr/bin/python3 - <<'PY'
import json, pathlib
root = pathlib.Path('/etc/reality-vless')
records = json.loads((root / 'clients.json').read_text())['clients']
assert len(records) == 2
assert len(json.loads((root / 'config.json').read_text())['inbounds'][0]['settings']['clients']) == 1
assert 'expired' in pathlib.Path('/tmp/reality-list.txt').read_text()
PY
realityctl renew test-phone --days 0 >/dev/null
realityctl show test-phone > /tmp/reality-test-phone-after.txt
/usr/bin/python3 - <<'PY'
import pathlib
before = [line for line in pathlib.Path('/tmp/reality-test-phone-before.txt').read_text().splitlines() if line.startswith('vless://')]
after = [line for line in pathlib.Path('/tmp/reality-test-phone-after.txt').read_text().splitlines() if line.startswith('vless://')]
assert len(before) == 1 and before == after
PY
invocation=$(systemctl show reality-vless -p InvocationID --value)
systemctl start reality-vless-expire.service
[[ $invocation == "$(systemctl show reality-vless -p InvocationID --value)" ]]
printf '4\n0\n' | realityctl >/dev/null
realityctl remove test-phone >/dev/null
systemctl is-active --quiet reality-vless
systemctl is-active --quiet reality-vless-expire.timer
/usr/bin/python3 - <<'PY'
import json, pathlib
records = json.loads(pathlib.Path('/etc/reality-vless/clients.json').read_text())['clients']
assert [r['name'] for r in records] == ['andrea']
PY
echo 'Upgrade, migration, expiry, retained-link renewal, menu, and removal smoke checks passed.'
