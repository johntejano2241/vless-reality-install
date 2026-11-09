#!/usr/bin/env bash
# Install the unprivileged Laravel dashboard and its narrow private host bridge.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
[[ -f /etc/reality-vless/config.json && -f "$base/dashboard/composer.lock" ]] || {
  echo 'Install/upgrade the VPN first and use a complete release with composer.lock.' >&2; exit 1;
}
port=${ADMIN_PORT:-8080}
if [[ -f /etc/reality-vless-admin/compose.env ]]; then
  port=$(python3 -c 'from pathlib import Path; print(dict(line.split("=",1) for line in Path("/etc/reality-vless-admin/compose.env").read_text().splitlines() if "=" in line)["ADMIN_PORT"])')
fi
[[ $port =~ ^[0-9]+$ && ${#port} -le 5 ]] || { echo 'Invalid ADMIN_PORT.' >&2; exit 1; }
((10#$port > 1023 && 10#$port <= 65535)) || { echo 'ADMIN_PORT must be between 1024 and 65535.' >&2; exit 1; }
admin_url=${ADMIN_URL:-http://localhost:$port}
python3 - "$admin_url" <<'PY'
import sys, urllib.parse
u=urllib.parse.urlsplit(sys.argv[1])
if u.username or u.password or u.query or u.fragment or u.path not in ['', '/']:
    raise SystemExit('ADMIN_URL must be an origin without credentials, path, query or fragment.')
if not u.hostname or (u.scheme != 'https' and not (u.scheme == 'http' and u.hostname in ['localhost','127.0.0.1'])):
    raise SystemExit('Use HTTPS for a public admin hostname, or HTTP localhost with an SSH tunnel.')
if any(c in sys.argv[1] for c in ['\n','\r','"',"'",' ','$','`']):
    raise SystemExit('Invalid ADMIN_URL characters.')
PY
if ! command -v docker >/dev/null; then
  apt-get update
  apt-get install -y docker.io docker-compose-v2
fi
docker compose version >/dev/null || { echo 'Install Docker Compose v2, then rerun install-admin.sh.' >&2; exit 1; }
systemctl enable --now docker
getent passwd reality-admin >/dev/null || useradd --system --user-group --no-create-home --shell /usr/sbin/nologin reality-admin
admin_uid=$(id -u reality-admin)
admin_gid=$(id -g reality-admin)
install -d -m 750 -o root -g reality-admin /etc/reality-vless-admin /var/lib/reality-vless-admin
install -d -m 700 /var/backups/reality-vless-admin
install -d -m 750 -o reality-admin -g reality-admin /var/lib/reality-vless-admin/database /var/lib/reality-vless-admin/storage
for directory in framework/cache/data framework/sessions framework/views logs app/private; do
  install -d -m 750 -o reality-admin -g reality-admin "/var/lib/reality-vless-admin/storage/$directory"
done
install -d -m 755 /opt/reality-vless-admin
# Persistent state is outside this directory; never copy a developer .env or database.
tar -C "$base/dashboard" --exclude=vendor --exclude=.env --exclude='*.sqlite*' --exclude=.phpunit.cache -cf - . |
  tar -C /opt/reality-vless-admin -xf -
install -m 755 "$base/admin_agent.py" /usr/local/lib/reality-vless/admin_agent.py
for unit in reality-vless-admin-agent.service reality-vless-admin-backup.service reality-vless-admin-backup.timer reality-vless-admin.service; do
  install -m 644 "$base/systemd/$unit" "/etc/systemd/system/$unit"
done
if [[ ! -f /etc/reality-vless-admin/app.env ]]; then
  app_key=$(python3 -c 'import secrets,base64; print("base64:"+base64.b64encode(secrets.token_bytes(32)).decode())')
  secure_cookie=true
  [[ $admin_url == https://* ]] || secure_cookie=false
  cat > /etc/reality-vless-admin/app.env <<ENV
APP_ENV=production
APP_DEBUG=false
APP_KEY=$app_key
APP_URL=$admin_url
DB_DATABASE=/var/lib/esmi/database/database.sqlite
SESSION_SECURE_COOKIE=$secure_cookie
CACHE_STORE=database
SESSION_DRIVER=database
QUEUE_CONNECTION=database
AGENT_DIRECTORY=/run/reality-vless-admin
ENV
  chmod 600 /etc/reality-vless-admin/app.env
fi
if [[ ! -f /etc/reality-vless-admin/compose.env ]]; then
  printf 'ADMIN_UID=%s\nADMIN_GID=%s\nADMIN_PORT=%s\n' "$admin_uid" "$admin_gid" "$port" > /etc/reality-vless-admin/compose.env
fi
if [[ ! -f /var/lib/reality-vless-admin/database/database.sqlite ]]; then
  install -m 600 -o reality-admin -g reality-admin /dev/null /var/lib/reality-vless-admin/database/database.sqlite
fi
systemctl daemon-reload
systemctl enable --now reality-vless-admin-agent
compose=(docker compose --env-file /etc/reality-vless-admin/compose.env -f /opt/reality-vless-admin/deploy/compose.yaml)
"${compose[@]}" build --pull
"${compose[@]}" run --rm --no-deps app php artisan migrate --force
"${compose[@]}" run --rm --no-deps app php artisan admin:refresh || echo 'Initial status refresh is pending; inspect the private agent.' >&2
systemctl enable reality-vless-admin
"${compose[@]}" up -d --force-recreate
systemctl start reality-vless-admin
systemctl enable --now reality-vless-admin-backup.timer
systemctl start reality-vless-admin-backup
ready=false
web_host=$(python3 -c 'from pathlib import Path; from urllib.parse import urlsplit; values=dict(line.split("=",1) for line in Path("/etc/reality-vless-admin/app.env").read_text().splitlines() if "=" in line); print(urlsplit(values["APP_URL"]).netloc)')
for _attempt in {1..15}; do
  if curl -fsS --max-time 5 -H "Host: $web_host" "http://127.0.0.1:$port/up" >/dev/null; then ready=true; break; fi
  sleep 2
done
[[ $ready == true ]] || { echo 'Dashboard health check failed. Inspect Docker logs before issuing a setup key.' >&2; exit 1; }
printf '\nAdmin dashboard installation complete. It listens only on 127.0.0.1:%s.\n' "$port"
printf 'For first setup, open an SSH tunnel: ssh -L %s:127.0.0.1:%s USER@SERVER\n' "$port" "$port"
# The raw eight-character key is emitted only after the web stack is ready.
"${compose[@]}" exec -T app php artisan admin:setup-key
