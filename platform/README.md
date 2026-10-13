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

The platform runs in its **own Railway project, `licensing`** (id `8fefc010-a153-4a9a-8a4c-be4df23a00a4`),
separate from the newsroom app: a `Postgres` service and a `player` service built from this
repository with root directory `/platform`, start command `npm run start:prod` (applies the
migrations, then starts Next) and health check `/api/health`. Railway no longer accepts
`railway.json` config-as-code, so those three settings live on the service itself; the
`railway.json` here is kept only as documentation of them.

Custom domain `player.oncue.cy` → Cloudflare zone `oncue.cy`, two records, both required:

| Type | Name | Value | Proxy |
| --- | --- | --- | --- |
| CNAME | `player` | the target Railway shows for the domain (`*.up.railway.app`) | DNS only (grey cloud) |
| TXT | `_railway-verify.player` | the `railway-verify=…` token Railway shows | n/a |

The certificate issues a few minutes after both records are live (see the main README's
"Cloudflare DNS" section for why the TXT matters). The target and token change if the
service is ever recreated: `railway domain status player.oncue.cy --service player`.

**Scripted** (Railway API token + Cloudflare token with Zone.DNS edit on `oncue.cy`):

```bash
RAILWAY_API_TOKEN=… CLOUDFLARE_API_TOKEN=… PLATFORM_ADMIN_PASSWORD=… python platform/deploy/provision.py
```

**With the Railway CLI** (what was actually used; `railway login --browserless` works from
a terminal without a browser):

```bash
railway link --project 8fefc010-a153-4a9a-8a4c-be4df23a00a4 --environment production
railway add --database postgres
railway add --service player --variables 'DATABASE_URL=${{Postgres.DATABASE_URL}}' \
  --variables PUBLIC_URL=https://player.oncue.cy --variables PLATFORM_ADMIN_PASSWORD=… \
  --variables PLATFORM_SESSION_SECRET=… --variables LICENSE_SIGNING_SECRET=…
railway api --var serviceId=… --var environmentId=… --var input='{"rootDirectory":"/platform","startCommand":"npm run start:prod","healthcheckPath":"/api/health"}' \
  'mutation($serviceId: String!, $environmentId: String!, $input: ServiceInstanceUpdateInput!) { serviceInstanceUpdate(serviceId: $serviceId, environmentId: $environmentId, input: $input) }'
railway service source connect --repo giannakkas/barpi --branch main --service player
railway domain player.oncue.cy --service player      # prints the CNAME target and the TXT token
```

The service deploys from branch `claude/barpi-monitor` until that branch is merged; then
switch it to `main` (`railway service source connect … --branch main`). Variables: see
"Environment" above; do **not** set `NODE_ENV`.
