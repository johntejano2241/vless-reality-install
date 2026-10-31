# VLESS + REALITY installer for Ubuntu 22.04

Install a dedicated Xray server and manage expiry and per-client public-IP slots through a menu or CLI.
Supports Ubuntu 22.04 with systemd on x86_64 and ARM64. It can run beside OpenVPN
using a separate service and an available TCP port.

Choose the guide for your server:

| Your situation | Guide | Script |
| --- | --- | --- |
| First time installing VLESS + REALITY on this server | [Fresh installation](#fresh-installation) | `install.sh` |
| VLESS + REALITY is already installed using this repository | [Update an existing installation](#update-an-existing-installation) | `upgrade.sh` |

Other guides: [Client menu](#client-menu) · [CLI commands](#cli-commands) · [Diagnostics](#diagnostics).

## Fresh installation

Use these steps for the **first installation on a server**. For a server already
running this project, follow [Update an existing installation](#update-an-existing-installation).

### 1. Prepare the server

Connect to your Ubuntu 22.04 server through SSH using an account with `sudo`
access. Install Git:

```bash
sudo apt-get update
sudo apt-get install -y git
```

### 2. Download the project

```bash
cd ~
git clone https://github.com/johntejano2241/vless-reality-install.git
cd vless-reality-install
```

Review the source before executing it with root privileges.

### 3. Run the installation script

```bash
sudo bash install.sh
```

Enter the three values requested by the installer:

| Installer prompt | What to enter |
| --- | --- |
| Public server IP or DNS hostname | Your server's public IPv4 address, or a DNS-only hostname resolving to it. Disable Cloudflare's ordinary HTTP proxy for this hostname. |
| REALITY target hostname | A reachable public TLS 1.3 hostname supporting HTTP/2. `www.microsoft.com` is an example to test; suitability depends on your server and network. |
| Listen TCP port | Press Enter for **443**, or choose another available TCP port. |

If a web server or OpenVPN already uses **TCP 443**, choose another port or a
separate IP/server. OpenVPN on UDP/TCP 1194 can coexist.

The installer checks the target certificate, TLS 1.3 and h2 negotiation, resolves
one official Xray release, and verifies GitHub's SHA-256 asset digest before
executing the binary. Missing digests cause installation to stop. This protects
download integrity; it is not an independent publisher signature.

### 4. Allow the selected TCP port

Allow the port in both your **host firewall** and **provider firewall**. For
example, if UFW is already active and you selected TCP 443:

```bash
sudo ufw allow 443/tcp
```

Replace `443` with your chosen port. The installer preserves existing firewall,
SSH, and OpenVPN settings.

### 5. Verify installation and add your first client

```bash
sudo systemctl is-active reality-vless reality-vless-expire.timer reality-vless-limits
sudo realityctl
```

The service check should print `active` for each of the three units. There are
initially zero authorized clients. In the menu, choose **1. Add client**, enter a
unique name, then choose expiration days and the device/public-IP slot limit.
See [Client menu](#client-menu) for the meaning of each value.

Import the generated `vless://` link into a client supporting VLESS + REALITY +
`xtls-rprx-vision`, such as Happ. Use the client's VPN mode for device-wide routing
and verify its DNS, IPv6, application exclusions, and kill-switch settings.

**Optional: pin a release for a fresh installation.** Instead of the normal
installation command in step 3, set `XRAY_VERSION` to an official release tag.
For example:

```bash
sudo env XRAY_VERSION=v26.10.29 bash install.sh
```

Use official Xray **26.10.29 or newer**. Re-running `install.sh` refuses existing
managed paths; use the update guide below for an existing installation.

## Update an existing installation

Use these steps when **VLESS + REALITY is already installed using this project**.
Run them on the server through SSH. This updates the client manager, expiry
scheduling, and IP-slot controller.

The installed Xray core must be **official Xray 26.10.29 or newer**. See
[Xray core updates](#xray-core-updates) below if the version check fails.

### 1. Download the latest project files

```bash
cd ~/vless-reality-install
git pull --ff-only
```

If your checkout is in a different directory, adjust the `cd` path. If Git
reports local edits or a conflicting history, review them before continuing.
Keep server credentials in `/etc/reality-vless/`, outside the repository.

### 2. Apply the update

```bash
sudo bash upgrade.sh
```

The script checks the installed Xray version before changing files. It creates
a backup under `/var/backups/reality-vless-upgrade.*` and prints the exact backup
path when the update completes.

Activating the private control socket may restart Xray once; connected clients
may briefly reconnect.

### 3. Verify the update and open the menu

```bash
sudo systemctl is-active reality-vless reality-vless-expire.timer reality-vless-limits
sudo realityctl list
sudo realityctl
```

The service check should print `active` for all three units. Confirm your clients
appear in the listing. If a unit is inactive or the update reports an error,
use [Diagnostics](#diagnostics) to inspect the relevant service.

### Settings preserved during updates

- Server keys, client UUIDs, and existing connection links.
- Active and expired client records, including their expiration settings.
- Previously configured public-IP slot limits.

Clients from a version without IP limits default to **Unlimited**. Accounts from
the original pre-expiry installer are imported with **no expiry**. Re-running
the update preserves existing settings.

The backup includes the installed manager and `/etc/reality-vless/`, plus any
existing expiry/controller files being replaced. Keep it private because it
contains server credentials.

### Xray core updates

`upgrade.sh` preserves the installed **Xray binary**. You can check its version:

```bash
/usr/local/bin/xray-reality version
```

If it is older than **26.10.29**, the manager update stops before changing files.
Update Xray separately using an [official release](https://github.com/XTLS/Xray-core/releases),
verify the download digest, back up the current binary, and validate the server
configuration before replacing it. Then run `sudo bash upgrade.sh` again.
This project currently has no automatic Xray core updater.

## Client menu

Run:

```bash
sudo realityctl
```

The menu provides:

1. **Add client** — enter a unique name, expiration days, then the device/IP-slot limit.
2. **Renew expired client** — retain the name and connection link, and choose a new expiry.
3. **Find client** — show its name, status, expiry date, and connection link.
4. **Show all clients** — show names, active/expired status, expiry dates, and IP-slot limits.
5. **Remove client** — permanently remove a record and disable its access.

Enter **0** to exit.

For Add and Renew:

- **0** means no expiry (`Never`).
- **1 or more** means that many 24-hour days from the Add or Renew operation.
- Negative values, fractions, and non-numeric values produce an error.

For Add, the next prompt is **Multiple devices / public-IP slots**:

- **0** means no limit.
- **1 or more** sets the allowed number of simultaneous source IPs for that client.
- Negative values, fractions, and non-numeric values produce an error.

The order is:

```text
Client name
Expiration days (0 = no expiry, 1 or more = days)
Multiple devices / public-IP slots (0 = no limit, 1 or more = limit)
```

### How IP slots work

As selected for this project, the limit counts **source IP addresses seen by the
server**, rather than physical devices. Several phones on the same Wi-Fi or
carrier NAT can share one slot. A phone switching between Wi-Fi and mobile data
may appear as a different IP. A physical-device limit cannot be reliably enforced
from a shared VLESS link.

For limited clients, new source IPs are initially denied and admitted through a
private local controller when capacity is available. The first request may fail
while a slot is admitted; retry after a few seconds. Excess IPs remain denied for
that client. Other accounts using the same IP retain their own access; no global
IP firewall bans are added.

Slots remain occupied while Xray reports live connections, including long-lived
streams. After all connections from an IP close, a **30-second idle grace** keeps
short browsing gaps from causing repeated admissions. The controller checks about
every five seconds while healthy. The free slot can then be used by a new
source IP. Changing networks may require the old connections to close first.

Slot admissions update Xray routing in memory, without restarting the server or
interrupting admitted streams. The on-disk config denies limited clients until
admitted, including after a reboot. If the controller or its statistics query
fails, new IPs remain denied for limited clients; already applied rules remain in
place. Check `reality-vless-limits` before diagnosing a blocked limited account.

Existing clients default to **Unlimited**. Renewal keeps the configured limit
and the same connection link. The limit is enforced by the server, not encoded
as an unsupported extra field in the `vless://` link.

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
sudo realityctl add phone --days 0 --devices 0
sudo realityctl add laptop --days 30 --devices 2

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

Add and Renew prompt for days when omitted in an interactive terminal. Add then
prompts for the device/IP-slot limit. Automated commands must supply `--days`;
`--devices` defaults to `0` when omitted non-interactively, preserving older
automation. Legacy command names remain available:
`show NAME` aliases `find NAME`, and `revoke NAME` aliases `remove NAME`.

Add, Renew, and Find print a private `vless://` link. Treat it as an access
credential and share it only with the intended user. The listing contains no
connection links. Clients have distinct random UUIDs; their REALITY transport
keys are shared at the server level.

## State and recovery

- `clients.json` is the authoritative account registry after migration. It keeps
  active and expired identities and expiry settings with root-only permissions.
- `config.json` contains only currently active client identities for Xray. The
  manager regenerates its client list from the registry; manual client edits
  made only to `config.json` will be replaced by the next sweep.
- `/run/reality-vless-limits/slots.json` stores transient admitted IPs and last-seen
  times with root-only permissions. The controller discards webhook destination
  fields instead of storing browsing history. Runtime slots are reset after reboot.
- The Xray statistics/routing API and admission notifications use private Unix
  sockets, with no public admin port. Notifications accept only the Xray service
  UID or root. The manager keeps destination security blocks ahead of client allow
  rules.
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
sudo systemctl status reality-vless-limits --no-pager
sudo journalctl -u reality-vless-limits -n 80 --no-pager
sudo systemctl list-timers reality-vless-expire.timer --all
sudo journalctl -u reality-vless-expire -n 80 --no-pager
sudo journalctl -u reality-vless -n 80 --no-pager
sudo /usr/local/bin/xray-reality run -test -config /etc/reality-vless/config.json
```

## Development and validation

```bash
bash -n install.sh upgrade.sh install-expiry.sh install-ip-limits.sh tests/smoke_upgrade.sh
python3 -m unittest discover -s tests -v
shellcheck install.sh upgrade.sh install-expiry.sh install-ip-limits.sh tests/smoke_upgrade.sh
```

GitHub Actions also validates empty, added, expired, renewed and removed client
configurations using a digest-verified Xray binary, then tests a legacy-state
upgrade and renewal on a disposable Ubuntu 22.04 runner with real systemd
services. It also exercises real VLESS + REALITY connections from different
source addresses: one-slot admission, same-IP sharing, excess-IP refusal,
independent unlimited accounts, uninterrupted admitted streams, and reuse after
disconnect. The CI smoke scripts refuse execution outside a disposable Actions
runner. CI does not establish connectivity from every phone or censored network.

## Upstream references

- https://github.com/XTLS/Xray-core
- https://xtls.github.io/en/config/inbounds/vless.html
- https://xtls.github.io/en/config/transports/reality.html

