"""Check each account lifecycle configuration with a real Xray binary."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

spec = importlib.util.spec_from_file_location('manager', Path(__file__).resolve().parents[1] / 'realityctl.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
binary = str(Path(sys.argv[1]).resolve())
now = datetime.now(timezone.utc)
private, _ = m.keypair()
config = m.make_config('www.microsoft.com', 443, private)
config['inbounds'][0]['streamSettings']['realitySettings']['shortIds'] = ['0123456789abcdef']
registry = {'version': 1, 'clients': []}
with tempfile.TemporaryDirectory() as tmp:
    for phase in ['empty', 'added', 'expired', 'renewed', 'removed']:
        moment = now
        if phase == 'added':
            registry = m.edit_clients(registry, 'add', 'phone', 1, now)
        elif phase in ['expired', 'renewed', 'removed']:
            moment = now + timedelta(days=2)
            if phase == 'renewed':
                registry = m.edit_clients(registry, 'renew', 'phone', 0, moment)
            elif phase == 'removed':
                registry = m.edit_clients(registry, 'remove', 'phone', None, moment)
        path = Path(tmp) / (phase + '.json')
        path.write_text(json.dumps(m.render_config(config, registry, moment)))
        subprocess.run([binary, 'run', '-test', '-config', str(path)], check=True)
        print(f'{phase}: Xray configuration accepted')
