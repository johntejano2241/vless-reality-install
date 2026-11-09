#!/usr/bin/env bash
# CI-only end-to-end installation; never run against an existing admin instance.
# shellcheck disable=SC2016
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 && ${GITHUB_ACTIONS:-false} == true && -f /tmp/reality-legacy-config.json ]] || {
  echo 'Requires the disposable native-manager CI fixture.' >&2; exit 1;
}
[[ ! -e /etc/reality-vless-admin ]] || { echo 'Refusing an existing admin installation.' >&2; exit 1; }
base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
temporary=$(mktemp -d)
trap 'rm -rf -- "$temporary"' EXIT
bash "$base/install-admin.sh" > "$temporary/first-install.log" 2>&1 || {
  sed -E '/Setup key:/d' "$temporary/first-install.log" >&2
  exit 1
}
python3 - "$temporary/first-install.log" <<'PY'
import html, http.cookiejar, re, sys, urllib.error, urllib.parse, urllib.request
text=open(sys.argv[1]).read()
keys=re.findall(r'^Setup key: ([A-Za-z0-9]{8})$',text,re.M)
assert len(keys)==1, 'Installation did not emit exactly one eight-character key'
assert text.index('Admin dashboard installation complete.')<text.index('Setup key: ')
opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
base='http://localhost:8080'
page=opener.open(base+'/setup').read().decode()
assert keys[0] not in page, 'Setup key leaked through HTML'
token=html.unescape(re.search(r'name="_token" value="([^"]+)"',page).group(1))
body=urllib.parse.urlencode({'_token':token,'setup_key':keys[0],'name':'CI Owner','email':'owner@example.test',
    'password':'Strong!Owner12345','password_confirmation':'Strong!Owner12345'}).encode()
bad_body=body.replace(urllib.parse.quote(token).encode(),b'invalid-csrf-token')
try: opener.open(urllib.request.Request(base+'/setup',data=bad_body,headers={'Origin':base})); raise AssertionError('Invalid CSRF token was accepted')
except urllib.error.HTTPError as error: assert error.code==419
response=opener.open(urllib.request.Request(base+'/setup',data=body,headers={'Origin':base,'Referer':base+'/setup'}))
assert '/admin/login' in response.url, 'First-admin creation did not redirect to login'
try: opener.open(base+'/setup'); raise AssertionError('Setup stayed open')
except urllib.error.HTTPError as error: assert error.code==404
print('First-admin setup: eight-character terminal key, HTTP claim and one-time closure passed.')
PY
compose=(docker compose --env-file /etc/reality-vless-admin/compose.env -f /opt/reality-vless-admin/deploy/compose.yaml)
# Install a synthetic MFA secret only in this disposable test account.
"${compose[@]}" exec -T app php -r 'require "vendor/autoload.php"; $app=require "bootstrap/app.php"; $app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap(); $u=App\Models\User::where("email","owner@example.test")->firstOrFail(); $u->saveAppAuthenticationSecret("JBSWY3DPEHPK3PXP");' >/dev/null
before=$("${compose[@]}" exec -T app php -r 'require "vendor/autoload.php"; $app=require "bootstrap/app.php"; $app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap(); echo hash("sha256",App\Models\User::firstOrFail()->password);')
bash "$base/install-admin.sh" > "$temporary/second-install.log" 2>&1 || {
  sed -E '/Setup key:/d' "$temporary/second-install.log" >&2
  exit 1
}
python3 -c 'import sys; assert "Setup key: " not in open(sys.argv[1]).read()' "$temporary/second-install.log"
after=$("${compose[@]}" exec -T app php -r 'require "vendor/autoload.php"; $app=require "bootstrap/app.php"; $app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap(); echo hash("sha256",App\Models\User::firstOrFail()->password);')
[[ $before == "$after" ]] || { echo 'Reinstallation changed admin credentials.' >&2; exit 1; }
"${compose[@]}" exec -T app php artisan admin:refresh >/dev/null
"${compose[@]}" exec -T app php -r 'require "vendor/autoload.php"; $app=require "bootstrap/app.php"; $app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap(); Illuminate\Support\Facades\Auth::login(App\Models\User::firstOrFail()); app(App\Services\VpnCommands::class)->submit(App\Models\Node::firstOrFail(),["action"=>"add","name"=>"web-smoke","days"=>7,"devices"=>1]);' >/dev/null
created=false
for _attempt in {1..20}; do
  if python3 -c 'import json; d=json.load(open("/etc/reality-vless/clients.json")); assert any(c["name"]=="web-smoke" for c in d["clients"])' 2>/dev/null; then created=true; break; fi
  sleep 2
done
[[ $created == true ]] || { echo 'Web queue failed to provision the account through the private agent.' >&2; "${compose[@]}" logs --tail=60 worker >&2; exit 1; }
systemctl start reality-vless-admin-backup.service
backup_file=$(find /var/backups/reality-vless-admin -maxdepth 1 -name '*.fernet' -type f | sort | tail -n1)
python3 /usr/local/lib/reality-vless/admin_agent.py verify-backup "$backup_file" >/dev/null
echo 'Admin installation, persistent credentials, native import, private queued provisioning and encrypted backup passed.'
