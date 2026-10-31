# VLESS + REALITY installer for Ubuntu 22.04

Install a dedicated Xray server and manage clients through a menu or CLI.
Supports Ubuntu 22.04 with systemd on x86_64 and ARM64. It can run beside OpenVPN
using a separate service and an available TCP port.

## Upgrade an existing installation

On your server, inside the existing checkout:

```bash
cd ~/vless-reality-install
git pull --ff-only
sudo bash upgrade.sh
sudo realityctl
```

`upgrade.sh` backs up the installed manager and `/etc/reality-vless/` under
`/var/backups/reality-vless-upgrade.*`, replaces the client manager, imports
existing accounts, and enables the expiry timer. It preserves the installed Xray
binary, server keys, client UUIDs, and connection links.

**Existing clients are imported with no expiry.** New clients use the expiry you
choose. Re-running the upgrade preserves existing expiry settings.

If the server uses a different checkout location, change the `cd` path. If Git
reports local edits, review them before updating; do not discard server changes
blindly. Server credentials belong in `/etc/reality-vless/`, never in this repo.

## Client menu

Run:

```bash
sudo realityctl
```

The menu provides:

1. **Add client** — enter a unique name and expiration days.
2. **Renew expired client** — retain the name and connection link, and choose a new expiry.
3. **Find client** — show its name, status, expiry date, and connection link.
4. **Show all clients** — show names, active/expired status, and expiry dates.
5. **Remove client** — permanently remove a record and disable its access.

Enter **0** to exit.

For Add and Renew:

- **0** means no expiry (`Never`).
- **1 or more** means that many 24-hour days from the Add or Renew operation.
- Negative values, fractions, and non-numeric values produce an error.

Expiration dates are displayed in **Philippine time (UTC+08:00)** and stored as
UTC timestamps. A client becomes expired at its expiration timestamp.

New names must be 1–48 letters, digits, underscores or hyphens, beginning with a
letter or digit. Add rejects an existing name regardless of capitalization,
including expired accounts. Find, Renew, and Remove accept an unambiguous
case-insensitive match. Legacy names that differ only by capitalization retain
their identities; use their exact capitalization to select one.

### Expired clients remain available for renewal

Expiry disables connection access while keeping the complete client record in
`/etc/reality-vless/clients.json`. It does not delete the name or UUID. Renewing
an expired client restores access through the **same existing link**; there is
no need to import a replacement into Happ or another compatible client.

Renew applies to **expired clients only**. Renewing an active or missing client
returns an error. To reuse an expired name, renew that record; Add will report
that the name already exists. Remove is the explicit permanent deletion action.

A systemd timer checks expiry every minute and shortly after boot. With a
healthy timer and service, access is normally disabled within about one minute
of expiry. Applying a changed access list restarts Xray, closing existing
connections; other active clients may briefly reconnect. An unchanged sweep or
client listing does not restart the service.

Enforcement depends on the timer and a successful service update. Check the
expiry-service journal if an update fails. Failed updates keep the client
records and are retried by later sweeps.

## CLI commands

```bash
# Add a client without expiry, or with 30 days of access
sudo realityctl add phone --days 0
sudo realityctl add laptop --days 30

# Renew an expired client for 7 days, or permanently
sudo realityctl renew laptop --days 7
sudo realityctl renew phone --days 0

# Find one client or list every retained record
sudo realityctl find phone
sudo realityctl list

# Explicit permanent removal (also removes expired records)
sudo realityctl remove phone

# Check service health or immediately apply due expirations
sudo realityctl status
sudo realityctl expire
```

Add and Renew prompt for days when omitted in an interactive terminal. Automated
commands must supply `--days`. Legacy command names remain available:
`show NAME` aliases `find NAME`, and `revoke NAME` aliases `remove NAME`.

Add, Renew, and Find print a private `vless://` link. Treat it as an access
credential and share it only with the intended user. The listing contains no
connection links. Clients have distinct random UUIDs; their REALITY transport
keys are shared at the server level.

## Fresh installation

Clone the project (install `git` first if needed):

```bash
git clone https://github.com/johntejano2241/vless-reality-install.git
cd vless-reality-install
sudo bash install.sh
sudo realityctl
```

Review the source before executing it with root privileges. The installer asks
for:

- Your server's public IPv4 address or a DNS-only hostname resolving to it.
  Cloudflare's ordinary HTTP proxy must be disabled for this server hostname.
- A reachable public TLS 1.3 hostname supporting HTTP/2 as the REALITY target.
  `www.microsoft.com` is an example to test, not a guarantee of suitability.
- An available TCP port, **443** by default. If a web server or OpenVPN uses
  TCP 443 already, choose another port or a separate IP/server. OpenVPN on
  UDP/TCP 1194 can coexist.

Allow the selected TCP port in both the host and provider firewalls. If UFW is
already active and you chose 443:

```bash
sudo ufw allow 443/tcp
```

Installation preserves existing firewall and SSH rules and OpenVPN settings.
There are initially zero authorized clients. Import the generated link into a
current client supporting VLESS + REALITY + `xtls-rprx-vision`, such as Happ.
Use the client's VPN mode for device-wide routing and verify its DNS, IPv6,
application exclusions, and kill-switch settings.

The installer checks the target certificate, TLS 1.3 and h2 negotiation, resolves
one official Xray release, and verifies GitHub's SHA-256 asset digest before
executing the binary. Missing digests cause installation to stop. This protects
download integrity; it is not an independent publisher signature. To request a
specific official release, replace the example tag:

```bash
sudo env XRAY_VERSION=vX.Y.Z bash install.sh
```

Re-running the fresh installer refuses existing managed paths. Use `upgrade.sh`
for the client-manager upgrade. Xray itself has no automatic updater here;
review upstream release notes, verify the replacement digest, and test before
updating the installed binary.

## State and recovery

- `clients.json` is the authoritative account registry after migration. It keeps
  active and expired identities and expiry settings with root-only permissions.
- `config.json` contains only currently active client identities for Xray. The
  manager regenerates its client list from the registry; manual client edits
  made only to `config.json` will be replaced by the next sweep.
- `server.json` holds link-generation metadata. Back up the whole
  `/etc/reality-vless/` directory securely so keys and registry stay together.
- Management operations and expiry sweeps use the same lock. The menu releases
  the lock between operations so waiting for input never blocks expiry checks.
- Configuration changes are validated by Xray before publishing. Ordinary
  validation/restart failures preserve or restore the previous records and
  configuration. A crash between atomic file replacements leaves the desired
  registry intact for the next sweep to reconcile.
- If recovery cannot restart Xray, inspect the journals and the root-only backup
  created by the upgrade. Never commit backups, private keys, or connection links.
- The runtime service uses a dedicated `reality-vless` account and restricted
  systemd permissions. The expiry manager runs as root to update credentials and
  restart the runtime service.
- Routing blocks common private, loopback and link-local destinations, including
  cloud metadata IPs. Use host/provider egress controls when stronger isolation
  is required.
- The listener binds IPv4. Native IPv6-only server endpoints are unsupported.
- Connection success on one network does not guarantee access through every
  firewall or continued availability in China.

## Diagnostics

```bash
sudo realityctl list
sudo systemctl status reality-vless --no-pager
sudo systemctl status reality-vless-expire.timer --no-pager
sudo systemctl list-timers reality-vless-expire.timer --all
sudo journalctl -u reality-vless-expire -n 80 --no-pager
sudo journalctl -u reality-vless -n 80 --no-pager
sudo /usr/local/bin/xray-reality run -test -config /etc/reality-vless/config.json
```

## Development and validation

```bash
bash -n install.sh upgrade.sh install-expiry.sh tests/smoke_upgrade.sh
python3 -m unittest discover -s tests -v
shellcheck install.sh upgrade.sh install-expiry.sh tests/smoke_upgrade.sh
```

GitHub Actions also validates empty, added, expired, renewed and removed client
configurations using a digest-verified Xray binary, then tests a legacy-state
upgrade and renewal on a disposable Ubuntu 22.04 runner with real systemd
services. The CI smoke script refuses execution outside a disposable Actions
runner. CI does not establish connectivity from every phone or censored network.

## Upstream references

- https://github.com/XTLS/Xray-core
- https://xtls.github.io/en/config/inbounds/vless.html
- https://xtls.github.io/en/config/transports/reality.html
