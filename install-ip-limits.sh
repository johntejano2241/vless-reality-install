#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
/usr/bin/python3 "$base/realityctl.py" check-core /usr/local/bin/xray-reality
install -m 755 "$base/ip_limiter.py" /usr/local/lib/reality-vless/ip_limiter.py
install -d -m 755 /etc/systemd/system/reality-vless.service.d
install -m 644 "$base/systemd/ip-control.conf" /etc/systemd/system/reality-vless.service.d/ip-control.conf
install -m 644 "$base/systemd/reality-vless-limits.service" /etc/systemd/system/reality-vless-limits.service
systemctl daemon-reload
/usr/bin/python3 /usr/local/lib/reality-vless/realityctl.py configure-limits
systemctl enable reality-vless-limits
systemctl reset-failed reality-vless-limits
systemctl restart reality-vless-limits
systemctl is-active --quiet reality-vless-limits
