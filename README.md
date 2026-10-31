# VLESS + REALITY installer for Ubuntu 22.04

A small, dedicated Xray server installer with named client creation and revocation.
Designed for a fresh Ubuntu 22.04 systemd VPS (x86_64 or ARM64). It runs beside
OpenVPN using its own binary, configuration, service, and TCP listener.

**Status:** local syntax and mocked lifecycle tests are available. Real Ubuntu
installation, client connectivity, and censorship resistance require deployment
validation. No guarantee of bypassing every firewall or the Great Firewall.

## Install

Clone this repository (install `git` first if it is missing):

```bash
git clone https://github.com/johntejano2241/vless-reality-install.git
cd vless-reality-install
```

Inspect `install.sh` and `realityctl.py`, then run:

```bash
sudo bash install.sh
```

The prompts request:

- Your server's public IPv4 address or DNS-only hostname resolving to its IPv4.
  Do not enable Cloudflare's ordinary HTTP proxy for this connection.
- A reachable public TLS 1.3 hostname supporting HTTP/2, used as the REALITY target.
  `www.microsoft.com` is an example to test, not a guarantee of suitability.
- An unused TCP port (443 by default). HTTPS already using TCP 443 requires a
  different port or a separate IP/server. OpenVPN on UDP 1194 can coexist.

The installer checks the target certificate, TLS 1.3, and h2 negotiation. It
resolves the latest official Xray release once and verifies GitHub's SHA-256
asset digest before executing it. It refuses releases without that digest.
To request a particular release, set `XRAY_VERSION` to an official `vX.Y.Z` tag:

```bash
sudo env XRAY_VERSION=vX.Y.Z bash install.sh
```

The digest protects download integrity but is not an independent publisher
signature. Installation requires working GitHub access from the VPS.

Allow inbound **TCP 443** (or the selected port) in both Ubuntu's firewall and
your VPS provider's firewall. If UFW is already active, for example:

```bash
sudo ufw allow 443/tcp
```

This installer does not enable, flush, disable, or rewrite your firewall, change
SSH settings, or touch OpenVPN. No NAT/IP-forwarding setup is required for this
application proxy. There are initially zero authorized clients.

## Add, list, show, revoke

```bash
sudo realityctl add phone
sudo realityctl add laptop
sudo realityctl list
sudo realityctl show phone
sudo realityctl revoke phone
sudo realityctl status
```

`add` and `show` print a private `vless://` link. Import it into a compatible
Hiddify, Happ, v2rayNG, or v2rayN client. Use a current client supporting
VLESS + REALITY + `xtls-rprx-vision`. Enable VPN/TUN mode for device-wide routing;
check client DNS, IPv6, routing exclusions and kill-switch behavior separately.
A system proxy alone does not tunnel every application.

Each client has a distinct random UUID. Revocation removes that UUID from the
server configuration and restarts Xray, closing current connections. All other
clients briefly disconnect and can reconnect with their existing links.
Do not share one client's link across users: revoking it affects all its copies.

## Security and operations

- Configuration is the source of truth; management commands are serialized with
  a lock. Each proposed change is tested by the installed Xray binary first.
- If service restart fails, the previous configuration is restored and a restart
  is attempted. Inspect the journal if recovery also fails.
- Root manages credentials; the service runs as `reality-vless` with only the
  capability to bind privileged ports and systemd filesystem restrictions.
- No passwords, Linux login accounts per client, web admin panel, cron deletion,
  traffic access log, or public subscription endpoint are created.
- Clients share server REALITY transport keys, while each has a separate VLESS
  UUID. Treat every exported link as a credential.
- Proxy routing blocks common private, loopback and link-local destinations,
  including cloud metadata addresses. This is defense in depth, not a complete
  network isolation boundary; use provider/host egress controls when required.
- Back up `/etc/reality-vless/` securely as root; it contains private credentials.
  Never commit it, connection links, or terminal output with credentials to Git.
- There is no automatic Xray updater. Review upstream changes, back up the binary
  and configuration, verify the replacement release digest, test the config and
  restart during a maintenance window. Ubuntu security updates remain separate.
- Installer re-runs refuse existing managed paths instead of rotating keys or
  overwriting users. If an interrupted install leaves partial files, inspect
  them and recover manually; the installer does not automatically delete them.
- The listener binds IPv4. Native IPv6-only server endpoints are not supported
  by this installer. The client connection still needs explicit IPv6 leak checks.

## Diagnostics

```bash
sudo journalctl -u reality-vless -n 80 --no-pager
sudo /usr/local/bin/xray-reality run -test -config /etc/reality-vless/config.json
sudo ss -ltnp
```

For connection failures check host/provider firewalls, port conflicts, target
reachability, client compatibility, SNI/public key/short ID, and server IP
blocking. A syntax-valid configuration does not prove end-to-end connectivity.

## Development checks

```bash
bash -n install.sh
python3 -m unittest discover -s tests -v
shellcheck install.sh
```

The included GitHub Actions workflow additionally downloads a digest-verified
current Xray release and checks empty, added-client and revoked-client configs.
That workflow must run after upload; it is not evidence of a completed VPS test.

## Upstream references

- https://github.com/XTLS/Xray-core
- https://xtls.github.io/en/config/inbounds/vless.html
- https://xtls.github.io/en/config/transport.html
- https://xtls.github.io/en/config/transports/reality.html
