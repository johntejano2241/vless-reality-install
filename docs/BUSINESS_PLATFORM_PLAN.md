# Esmi VPN — administrator platform plan

Prepared for John Michael C. Tejano · 9 November 2026

The approved product is an **administrator-only VPN platform**. Customer Portal and Payment Services are removed. All web accounts belong to staff. Customer/contact records are managed internally and have no web login. The platform contains no checkout, payment processing, invoices, finance roles or revenue dashboard.

## Delivered scope

| Area | Behavior |
| --- | --- |
| Initial setup | The installer prints exactly eight random alphanumeric characters after web health succeeds. The first owner uses the key at /setup to choose credentials. |
| Authentication | Strong passwords, required authenticator MFA, encrypted MFA secrets, recovery codes and session revocation after staff changes. |
| Staff | Owner, operator and support permissions enforced in server methods. The last active owner cannot be disabled or demoted. |
| Dashboard | Active/expired/suspended accounts, failed operations, stale server data, aggregate traffic and a usage chart. |
| VPN accounts | Import, add, extend active/expired access, suspend/resume, edit public-IP slots, rotate credentials and remove accounts. Zero days means no expiry; zero slots means unlimited. |
| Customer records | Contact information, internal notes and account assignments; no customer credentials. |
| Access plans | Named duration, public-IP allowance and region templates; assignment does not silently modify existing access. |
| Servers | Private node connections, service/resource health, account observations and refresh timestamps. |
| Operations | Durable queue, root-registry idempotency receipts, stale-state checks, retry/failure visibility and interrupted-work recovery. |
| Support and audit | Internal support records, privileged-action history and in-dashboard health/failure notifications. |
| Backups | Daily encryption, a separately stored key and isolated verification/restore rehearsal. |

The native Esmi Android client remains its own project. This release works with existing clients such as Happ and does not produce an Android APK.

## First-owner setup

1. Install the native manager and admin stack. The installer prepares persistent storage, applies database migrations, starts services and checks web health.
2. The server terminal then displays a cryptographically random **eight-character** setup key. There is no shared default value.
3. Open an SSH tunnel and visit http://localhost:8080/setup from the administrator's computer.
4. Enter the key and choose the owner's name, email and strong password.
5. A database transaction consumes the key and creates the first owner. Setup closes with HTTP 404.
6. Sign in at /admin/login, enroll an authenticator and save recovery codes privately.

Only a password hash of the key is stored. It expires after 30 minutes, requests are throttled, and ten global wrong attempts invalidate it. The key is not an admin password, permanent API key, URL token or HTML field value. A conditional database update prevents simultaneous successful claims.

If an administrator already exists, reinstall/upgrade preserves credentials and emits no new setup key. Completed setup stays closed even if records are later deleted outside the application. Rotate an expired unclaimed key from the server console. Existing-account recovery is a separate root-console command requiring MFA re-enrollment.

## Architecture

The implementation uses Laravel 13, Filament 5, PHP 8.4 containers, an unprivileged Nginx proxy and persistent SQLite. Database-backed queue/cache/sessions keep this single-host pilot smaller than the former customer-portal/payment architecture. Composer dependencies are pinned in the committed lockfile.

The PHP runtime uses the dedicated reality-admin OS identity. It has no Docker socket, SSH credentials, unrestricted root shell or REALITY private-key file. PHP/worker/scheduler have internal networking; only the Nginx proxy joins the bridge needed for its loopback-published listener. Containers use read-only roots, dropped capabilities and restrictive persistent-directory ownership.

A narrow root Python agent accepts fixed, validated operations from OS-authorized Unix-socket peers. It uses the existing native manager's lock, validation and atomic publishing. The native registry remains authoritative; the dashboard database owns staff/customer metadata and observed state. The web app does not independently regenerate Xray configuration.

The default web listener is 127.0.0.1:8080. Public administration requires an operator-configured HTTPS reverse proxy/access gateway and correct application URL/cookie settings. Setting ADMIN_URL does not provision DNS, TLS or a public listener. Keep the admin hostname separate from the raw VPN endpoint.

Additional nodes need the same manager/agent plus an operator-provisioned, authenticated restricted transport exposing each socket under the approved local directory. Registering a server row does not install a VPS or provide automatic failover.

## Roles and access operations

| Role | Work |
| --- | --- |
| Owner | All administration, staff/servers/audit and password-confirmed VPN profile reveal. |
| Operator | VPN changes, customer/plan editing, assignments, refresh and support work. |
| Support | Operational/customer read access and internal support-record editing. |

The owner creates additional staff; there is no public registration. Disabled/demoted staff lose sessions and permissions. Queued commands recheck the submitting user's current authorization.

Create a customer record, choose a plan template, queue a named VPN account, wait for acknowledgement, refresh observed state, assign metadata, and privately distribute its profile. A form submission alone is not proof of applied access.

Extension uses the later of current expiry or current time. Extending suspended access does not resume it. Resume requires valid access. Rotation changes the UUID while retaining expiry, so old distributed profiles stop working. Rotation/removal require typing the exact account name.

Stable command UUIDs and durable root receipts prevent retrying an extension twice. Observed client versions reject delayed work after newer suspension, rotation or CLI changes. Resolve the cause and submit a fresh intentional request after a stale-state failure.

## Device limits and service behavior

Public-IP slots cannot distinguish two Happ phones behind the same Wi-Fi or carrier NAT. A single phone changing networks can consume multiple addresses. This release includes IP-limit editing and diagnostics, and labels the control honestly.

Strict physical-device binding, Happ vendor enrollment and device-proof tunnel authentication are not implemented. Copyable hardware headers, TCP counts or source-port counts would not provide that guarantee. A branded app that receives an ordinary reusable UUID alone would not solve credential copying either.

Access-list changes can restart Xray and briefly reconnect other accounts on the same node. This supports the current manager's revocation/expiry behavior; it is not seamless per-user disconnection. Measure interruption rates during the invited pilot.

Local expiry and last accepted VPN policy continue without the web app. A disconnected node cannot apply a new suspension until management connectivity recovers. Mark it stale rather than reporting success.

## Monitoring and recovery

Servers refresh every minute; cached UI data is marked stale after three minutes. Unavailable statistics are Unknown. Resource samples include load, memory and disk. Owners receive internal notifications for unhealthy/unreachable nodes, low disk and exhausted retries; external messaging is not configured.

Observed aggregate traffic handles repeated polls and counter epochs. A crash can lose the final sampling interval. These numbers are not precise billing counters or enforced hard GB quotas.

Daily encrypted backups contain matched VPN files, the application environment and a consistent SQLite copy. The root-only backup key is outside the archive. Keep encrypted copies and the key securely off-host; automatic upload/retention pruning are not configured.

The verification command authenticates an archive, rejects unsafe members, restores only to a private temporary directory and validates JSON/SQLite integrity. Production restoration remains a supervised procedure: stop writers, preserve current state, restore a matched verified snapshot with original ownership/key, validate Xray, reconcile pending work/expiry and retain a rollback copy.

## Deployment and pilot

See [ADMIN_DASHBOARD.md](ADMIN_DASHBOARD.md) for separate fresh-install/update commands, first setup, optional HTTPS, key rotation, account recovery, node transport and diagnostics.

Automated validation covers native/agent lifecycle, real Xray upgrade and REALITY IP control, setup/roles/MFA, dependency audit, template compilation, containers, full installation/reinstallation, private queued provisioning, encrypted backup verification and browser acceptance. The pull request and Actions results identify the passing revision. This is not an independent penetration-test claim.

Before production use, preserve/verify a backup; enroll the owner; compare imported accounts and existing profiles; exercise lifecycle/active-stream behavior with synthetic users; test two Android phones on shared and different networks; rehearse outage/recovery; configure off-host backup handling; and measure traffic/support demand during an invited pilot.

The existing 2-vCPU/4-GB server is a candidate pilot host, not a guaranteed simultaneous-user capacity. Egress, throughput, concurrent streams, container memory and support load determine practical capacity. Business accounting remains outside this application.

No production VPS access, customer migration, external notifications or physical Android acceptance is implied by CI results.

Implementation: [PR #3](https://github.com/johntejano2241/vless-reality-install/pull/3).
