#!/usr/bin/env bash
# Upgrade the client manager; preserve the installed Xray binary, keys and UUIDs.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
# shellcheck disable=SC1091
source /etc/os-release
[[ $ID == ubuntu && $VERSION_ID == 22.04 ]] || { echo 'Requires Ubuntu 22.04.' >&2; exit 1; }
[[ -d /run/systemd/system ]] || { echo 'Requires systemd.' >&2; exit 1; }
base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
for source_file in realityctl.py ip_limiter.py install-ip-limits.sh install-expiry.sh systemd/ip-control.conf systemd/reality-vless-limits.service systemd/reality-vless-expire.service systemd/reality-vless-expire.timer; do
  [[ -f "$base/$source_file" ]] || { echo "Missing project file: $source_file" >&2; exit 1; }
done
for installed_file in /etc/reality-vless/config.json /etc/reality-vless/server.json /usr/local/lib/reality-vless/realityctl.py /usr/local/bin/xray-reality /etc/systemd/system/reality-vless.service; do
  [[ -f $installed_file ]] || { echo "Existing installation missing: $installed_file" >&2; exit 1; }
done
/usr/bin/python3 "$base/realityctl.py" check-core /usr/local/bin/xray-reality
exec 9>>/run/lock/reality-installer.lock
flock -n 9 || { echo 'Another installation or upgrade is running.' >&2; exit 1; }
# Validate source without creating pycache beside the checked-out project.
python3 - "$base/realityctl.py" <<'PY'
import pathlib, sys
compile(pathlib.Path(sys.argv[1]).read_text(), sys.argv[1], 'exec')
PY
backup=$(mktemp -d /var/backups/reality-vless-upgrade.XXXXXXXX)
# Snapshot under the same lock used by CLI commands and the expiry timer. Release
# it before invoking the new manager, which acquires that lock itself.
(
  flock -x 8
  cp -a /etc/reality-vless "$backup/state"
  cp -p /usr/local/lib/reality-vless/realityctl.py "$backup/realityctl.py"
  if [[ -f /usr/local/lib/reality-vless/ip_limiter.py ]]; then
    cp -p /usr/local/lib/reality-vless/ip_limiter.py "$backup/ip_limiter.py"
  fi
  if [[ -f /etc/systemd/system/reality-vless.service.d/ip-control.conf ]]; then
    cp -p /etc/systemd/system/reality-vless.service.d/ip-control.conf "$backup/ip-control.conf"
  fi
  for unit in reality-vless-expire.service reality-vless-expire.timer reality-vless-limits.service; do
    if [[ -f /etc/systemd/system/$unit ]]; then
      cp -p "/etc/systemd/system/$unit" "$backup/$unit"
    fi
  done
  manager_tmp=$(mktemp /usr/local/lib/reality-vless/.realityctl.XXXXXXXX)
  install -m 755 "$base/realityctl.py" "$manager_tmp"
  mv -f -- "$manager_tmp" /usr/local/lib/reality-vless/realityctl.py
) 8>>/run/lock/realityctl.lock
if ! /usr/bin/python3 /usr/local/lib/reality-vless/realityctl.py migrate; then
  # Migration validation does not alter the running Xray config. Restore the old
  # manager under lock; keep the snapshot for inspection rather than deleting data.
  (
    flock -x 8
    restore_tmp=$(mktemp /usr/local/lib/reality-vless/.realityctl.XXXXXXXX)
    install -m 755 "$backup/realityctl.py" "$restore_tmp"
    mv -f -- "$restore_tmp" /usr/local/lib/reality-vless/realityctl.py
  ) 8>>/run/lock/realityctl.lock
  echo "Migration failed; old manager restored. Backup: $backup" >&2
  exit 1
fi
ln -sfn /usr/local/lib/reality-vless/realityctl.py /usr/local/bin/realityctl
if ! bash "$base/install-ip-limits.sh"; then
  echo "Manager updated, but IP-limit setup failed. Fix the error and rerun upgrade.sh. Backup: $backup" >&2
  exit 1
fi
if ! bash "$base/install-expiry.sh"; then
  echo "Manager updated, but expiry scheduling failed. Fix the error and rerun upgrade.sh. Backup: $backup" >&2
  exit 1
fi
printf '\nUpgrade complete. Existing clients and connection links preserved.\n'
printf 'Backup: %s\nOpen the menu: sudo realityctl\n' "$backup"

