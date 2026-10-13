# Licensing platform (player.oncue.cy)

Manages the serial keys for the **Monitoring Application** (`../monitor`): create keys,
see which computers activated them and when they last checked in, lock or unlock a whole
licence or a single computer, revoke, and keep an activity log. The program checks in every
few minutes; a lock takes effect within one check-in.

Stack: the same as the newsroom app next door (Next.js 16, Prisma 7 on PostgreSQL,
Tailwind 4), one admin password, HMAC-signed session cookie.

## How a program is licensed

1. On first start the program asks for a key (`ONCUE-XXXXX-XXXXX-XXXXX-XXXXX`, shown on the
   licence page here) and posts it with a computer id to `POST /api/v1/activate`.
   The platform registers the computer (if the licence has a free seat) and returns an
   activation token.
2. Every `LICENSE_CHECK_INTERVAL` seconds (default 300) the program posts to
   `POST /api/v1/heartbeat`. The answer is `active` or `locked` (with the message you typed),
   or `revoked` / `expired` / `unknown`, after which the program asks for a key again.
3. If the platform cannot be reached the program keeps running on its last answer for
   72 hours, then locks itself until it can check in.

Computer ids are a hash of the Windows machine id and host name, not personal data.

### Device API

| Endpoint | Body (JSON) | Answers |
| --- | --- | --- |
| `POST /api/v1/activate` | `key, machine_id, hostname, os, version, product` | 200 `active`/`locked` + `token`; 403 `locked`/`revoked`/`expired`/`no_seats`; 404 `invalid` |
| `POST /api/v1/heartbeat` | `key, machine_id, token, version, hostname` | 200 `active`/`locked`; 403 `revoked`/`expired`; 404/401 `unknown` |
| `POST /api/v1/deactivate` | `key, machine_id, token` | 200 `ok` |

Every answer carries `status`, `message` and `interval` (seconds until the next check-in).

### Admin API

The pages post plain HTML forms to these; with `Content-Type: application/json` they
answer JSON instead of redirecting. All need the session cookie from `POST /api/auth/login`.

| Endpoint | Fields |
| --- | --- |
| `POST /api/admin/licenses` | `label, maxSeats, expiresAt (YYYY-MM-DD), notes, product` |
| `POST /api/admin/licenses/:id` | `action = update \| lock \| unlock \| revoke \| reinstate \| delete`, `message`, and the update fields |
| `POST /api/admin/systems/:id` | `action = lock \| unlock \| remove`, `message` |

## Running locally

```bash
cd platform
npm install
cp .env.example .env            # fill in DATABASE_URL and the secrets
npx prisma migrate deploy
npm run dev                     # http://localhost:3006
```

To point a program at it: `BarpiMonitor.exe --license-server http://localhost:3006`
(or set `BARPI_LICENSE_SERVER`).

## Environment

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL. On Railway: `${{Postgres.DATABASE_URL}}?schema=licensing`, its own schema in the barpi database |
| `PLATFORM_ADMIN_PASSWORD` | The admin password |
| `PLATFORM_SESSION_SECRET` | Signs the admin cookie (16+ chars) |
| `LICENSE_SIGNING_SECRET` | Signs activation tokens (16+ chars); changing it makes every computer activate again |
| `PUBLIC_URL` | `https://player.oncue.cy` |
| `LICENSE_CHECK_INTERVAL` | Optional; seconds between check-ins (default 300) |

## Deployment (Railway + Cloudflare)

The platform is a second service in the existing Railway project, built from this
repository with root directory `platform`.

**Scripted.** With a Railway API token and a Cloudflare API token (Zone.DNS edit on
`oncue.cy`) in the environment:

```bash
RAILWAY_API_TOKEN=… CLOUDFLARE_API_TOKEN=… PLATFORM_ADMIN_PASSWORD=… python platform/deploy/provision.py
```

`deploy/provision.py` creates the `player` service, sets its root directory, config file
and variables, attaches `player.oncue.cy`, creates the CNAME and the `_railway-verify`
TXT in Cloudflare (proxy off, as the main README explains), and triggers a deployment.
It was written without a token to try it against, so if Railway refuses a call it prints
the error and the manual steps below cover the rest.

**By hand.**

1. Railway → project `barpi` → *New* → *GitHub repo* → `giannakkas/barpi`, branch `main`.
   Name the service `player`.
2. Service *Settings*: Root directory `platform`; Config-as-code file `platform/railway.json`.
3. *Variables*: `DATABASE_URL = ${{Postgres.DATABASE_URL}}?schema=licensing`,
   `PLATFORM_ADMIN_PASSWORD`, `PLATFORM_SESSION_SECRET`, `LICENSE_SIGNING_SECRET` (long
   random strings), `PUBLIC_URL = https://player.oncue.cy`. Do **not** set `NODE_ENV`.
4. *Settings → Networking → Custom domain*: `player.oncue.cy`, target port **8080**.
   Railway prints a CNAME and a `_railway-verify` TXT record.
5. Cloudflare → `oncue.cy` → DNS: add both records, CNAME with the proxy **off** (grey
   cloud). The certificate issues a few minutes after the TXT is live; after that the
   proxy may be turned on with SSL mode Full (strict).
6. Deploy. `npm run start:prod` applies the migrations and starts the server; the health
   check is `/api/health`.

The programs are built with `https://player.oncue.cy` as their platform, so once the
domain answers, existing installations start checking in without a new build.
