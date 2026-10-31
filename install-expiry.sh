#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
install -m 644 "$base/systemd/reality-vless-expire.service" /etc/systemd/system/reality-vless-expire.service
install -m 644 "$base/systemd/reality-vless-expire.timer" /etc/systemd/system/reality-vless-expire.timer
systemctl daemon-reload
# Sweep immediately, including after a reboot or a missed timer while powered off.
systemctl start reality-vless-expire.service
systemctl enable --now reality-vless-expire.timer
systemctl is-active --quiet reality-vless-expire.timer

