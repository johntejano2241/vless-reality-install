#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
# shellcheck disable=SC1091
source /etc/os-release
[[ $ID == ubuntu && $VERSION_ID == 22.04 ]] || { echo 'Requires Ubuntu 22.04.' >&2; exit 1; }
[[ -d /run/systemd/system ]] || { echo 'Requires systemd.' >&2; exit 1; }
base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
[[ -f "$base/realityctl.py" ]] || { echo 'Extract the complete project first.' >&2; exit 1; }
exec 9>/run/lock/reality-installer.lock
flock -n 9 || { echo 'Another installation is running.' >&2; exit 1; }
for path in /etc/reality-vless /usr/local/lib/reality-vless /usr/local/bin/realityctl /usr/local/bin/xray-reality /etc/systemd/system/reality-vless.service; do
  [[ ! -e $path ]] || { echo "Refusing to overwrite $path. Use realityctl for existing installations." >&2; exit 1; }
done
read -r -p 'Public server IP or DNS hostname (DNS-only, no CDN proxy): ' endpoint
read -r -p 'REALITY target hostname (reachable TLS 1.3 site, e.g. www.microsoft.com): ' sni
read -r -p 'Listen TCP port [443]: ' port
port=${port:-443}
[[ $port =~ ^[0-9]+$ && ${#port} -le 5 ]] && ((10#$port >= 1 && 10#$port <= 65535)) || { echo 'Invalid port.' >&2; exit 1; }
port=$((10#$port))
[[ -z $(ss -H -ltn "sport = :$port") ]] || { echo 'TCP port is already occupied.' >&2; exit 1; }
apt-get update
apt-get install -y ca-certificates curl unzip jq python3 python3-cryptography openssl
python3 "$base/realityctl.py" check-input "$endpoint" "$sni"
echo 'Checking target TLS 1.3 and h2 support...'
tls=$(timeout 20 openssl s_client -connect "$sni:443" -servername "$sni" -tls1_3 -alpn h2 -verify_return_error -verify_hostname "$sni" </dev/null 2>&1) || { echo 'Target TLS verification failed.' >&2; exit 1; }
[[ $tls == *'ALPN protocol: h2'* ]] || { echo 'Choose a target supporting h2.' >&2; exit 1; }
case $(uname -m) in x86_64) asset=Xray-linux-64.zip;; aarch64) asset=Xray-linux-arm64-v8a.zip;; *) echo 'Supported CPUs: x86_64 and aarch64.' >&2; exit 1;; esac
tmp=$(mktemp -d)
trap 'rm -rf -- "$tmp"' EXIT
# Resolve a release once. Verify GitHub's SHA-256 asset digest before extracting.
# XRAY_VERSION may pin a release, e.g. vX.Y.Z. No unverified remote shell is executed.
release=${XRAY_VERSION:-latest}
[[ $release == latest || $release =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'Invalid XRAY_VERSION.' >&2; exit 1; }
api=https://api.github.com/repos/XTLS/Xray-core/releases/latest
[[ $release == latest ]] || api="https://api.github.com/repos/XTLS/Xray-core/releases/tags/$release"
curl --proto '=https' --tlsv1.2 -fsSL --retry 3 --max-time 60 "$api" -o "$tmp/release.json"
url=$(jq -er --arg name "$asset" '.assets[] | select(.name==$name) | .browser_download_url' "$tmp/release.json")
digest=$(jq -er --arg name "$asset" '.assets[] | select(.name==$name) | .digest' "$tmp/release.json")
[[ $url == https://github.com/XTLS/Xray-core/releases/download/* && $digest =~ ^sha256:[a-f0-9]{64}$ ]] || { echo 'Missing trusted SHA-256 digest; refusing installation.' >&2; exit 1; }
curl --proto '=https' --tlsv1.2 -fsSL --retry 3 --max-time 180 "$url" -o "$tmp/xray.zip"
printf '%s  %s\n' "${digest#sha256:}" "$tmp/xray.zip" | sha256sum -c -
unzip -p "$tmp/xray.zip" xray > "$tmp/xray"
chmod 700 "$tmp/xray"
"$tmp/xray" version
# No service or persistent configuration has been changed before verification.
getent passwd reality-vless >/dev/null || useradd --system --user-group --no-create-home --shell /usr/sbin/nologin reality-vless
install -d -m 750 -o root -g reality-vless /etc/reality-vless
install -d -m 755 /usr/local/lib/reality-vless
install -m 755 "$tmp/xray" /usr/local/bin/xray-reality
install -m 755 "$base/realityctl.py" /usr/local/lib/reality-vless/realityctl.py
ln -s /usr/local/lib/reality-vless/realityctl.py /usr/local/bin/realityctl
python3 /usr/local/bin/realityctl init "$endpoint" "$sni" "$port"
cat > /etc/systemd/system/reality-vless.service <<'UNIT'
[Unit]
Description=Managed VLESS REALITY server
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=5
[Service]
User=reality-vless
Group=reality-vless
ExecStart=/usr/local/bin/xray-reality run -config /etc/reality-vless/config.json
Restart=on-failure
RestartSec=5
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
UMask=0077
LimitNOFILE=65536
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now reality-vless
systemctl is-active --quiet reality-vless
printf '\nInstalled. No clients exist yet. Run: sudo realityctl add phone\n'
printf 'Allow inbound TCP %s in your host AND provider firewalls. Existing firewall/SSH rules were preserved.\n' "$port"
printf 'Release: %s\n' "$(jq -r .tag_name "$tmp/release.json")"
