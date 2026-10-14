# Licensing platform (license.oncue.cy)

Serial keys for every software you ship, kept per **customer** and per **software**:
register each software (its *slug* is what the program sends as `product`), keep the
customers, create keys, see which computers activated them and when they last checked in,
lock or unlock a whole licence or a single computer, revoke, and keep an activity log. The
programs check in every few minutes; a lock takes effect within one check-in. The
**Monitoring Application** (`../monitor`) is the first software; any other program uses the
same device API with its own slug.

Stack: the same as the newsroom app next door (Next.js 16, Prisma 7 on PostgreSQL,
Tailwind 4), one admin password, HMAC-signed session cookie.

## How a program is licensed

1. On first start the program asks for a key (`ONCUE-XXXXX-XXXXX-XXXXX-XXXXX`, shown on the
   licence page here) and posts it with a computer id and its software slug (`product`) to
   `POST /api/v1/activate`. A key issued for another software is refused. The platform
   registers the computer (if the licence has a free seat) and returns an activation token.
2. Every `LICENSE_CHECK_INTERVAL` seconds (default 300) the program posts to
   `POST /api/v1/heartbeat`. The answer is `active` or `locked` (with the message you typed),
   or `revoked` / `expired` / `unknown`, after which the program asks for a key again.
3. If the platform cannot be reached the program keeps running on its last answer for
   72 hours, then locks itself until it can check in.
4. A computer with **no internet** gets an *offline licence file* instead (see below): the
   program imports it and runs until the file's expiry without any server. If that computer
   does get a connection it checks in like the others, so a lock or revoke still reaches it.

Computer ids are a hash of the Windows machine id and host name, not personal data.

### Device API

| Endpoint | Body (JSON) | Answers |
| --- | --- | --- |
| `POST /api/v1/activate` | `key, machine_id, hostname, os, version, product` | 200 `active`/`locked` + `token`; 403 `locked`/`revoked`/`expired`/`no_seats`; 404 `invalid` |
| `POST /api/v1/heartbeat` | `key, machine_id, token, version, hostname` | 200 `active`/`locked`; 403 `revoked`/`expired`; 404/401 `unknown` |
| `POST /api/v1/deactivate` | `key, machine_id, token` | 200 `ok` |
| `GET /api/v1/public-key` | — | the RSA public key programs embed to verify offline files (`n`, `e`, `pem`) |

Every answer carries `status`, `message` and `interval` (seconds until the next check-in).

### Admin API

The pages post plain HTML forms to these; with `Content-Type: application/json` they
answer JSON instead of redirecting. All need the session cookie from `POST /api/auth/login`.

| Endpoint | Fields |
| --- | --- |
| `POST /api/admin/licenses` | `productId` or `product` (slug); `customerId`, or `customerName` (+ `customerEmail`) to create the customer; `label` (a reference such as site or invoice), `maxSeats`, `expiresAt (YYYY-MM-DD)`, `notes` |
| `POST /api/admin/licenses/:id` | `action = update \| extend \| offline \| lock \| unlock \| revoke \| reinstate \| delete`, `message`; update: `customerId, productId, label, maxSeats, expiresAt, notes`; extend: `months` (1/3/6/12) or `until`, `back`; offline: `machineId, hostname, expiresAt` (answers the `.lic` file, or JSON with `content`) |
| `GET /api/admin/systems/:id/file` | the current offline file of a computer (re-signed from the licence as it is now) |
| `PUT /api/admin/products/:id/releases` | upload a build: raw body + headers `x-filename`, `x-version`, `x-notes` (URL-encoded) and `x-size`; outside the proxy layer (which caps bodies at 10 MB), so it verifies the session cookie itself |
| `POST /api/admin/releases/:id` | `action = delete` |
| `GET /download/:slug` · `GET /download/:slug/:release` | **public**: the latest build of a software, or one specific build |
| `POST /api/admin/systems/:id` | `action = lock \| unlock \| remove`, `message` |
| `POST /api/admin/products` | `name`, `slug` (optional, derived from the name), `notes` |
| `POST /api/admin/products/:id` | `action = update \| delete` (delete takes its licences, computers and builds with it), `name, slug, notes` |
| `POST /api/admin/customers` | `name`, `email`, `phone`, `notes` |
| `POST /api/admin/customers/:id` | `action = update \| delete` (delete takes its licences and computers with it), `name, email, phone, notes` |

### Adding a software

Software → New software, give it a name (the slug is derived, e.g. `playout-server`). The
program must send that slug as `product` in every device call; the software page shows the
exact body. Keys are created per customer and software from the Licences page, or from the
customer's or the software's own page.

## Offline licence files

A computer without internet cannot activate a key, so the platform issues it a signed file
instead. On the licence page, "Offline licence file": paste the 20-character computer ID the
program shows (Copy ID on its activation screen), set the validity, and download the `.lic`
file; the operator imports it with "Import licence file…". The file is bound to that computer
and software and counts as one seat. **Extend** on the dashboard (or the licence page) moves
the licence's expiry and the file's expiry together; download the file again and hand it over.
A lock or revoke cannot reach a computer that never connects, so keep offline validity short.

The signature is RSASSA-PKCS1-v1_5 / SHA-256 with an RSA-2048 key. Generate the pair once:

```bash
node platform/deploy/keygen.mjs
```

Put the private key in `LICENSE_FILE_PRIVATE_KEY` (Railway variable) and the public modulus
in each program (`PUBLIC_KEY_N` in `monitor/barpi_monitor/license.py`); `/api/v1/public-key`
publishes it too. Losing or rotating the private key invalidates every issued file and needs
new program builds, so keep it safe.

## Downloads

Each software has a Downloads panel: upload the exe or installer with its version, and give
customers the public link `https://license.oncue.cy/download/<slug>` (always the latest build;
`/download/<slug>/<release id>` for a specific one). Files live on the downloads volume
(`DOWNLOADS_DIR`, a Railway volume mounted at `/data`); the database keeps version, size,
SHA-256 and a download counter. Uploads stream straight to disk, so large builds are fine.

## Running locally

```bash
cd platform
npm install
cp .env.example .env            # fill in DATABASE_URL and the secrets
npx prisma migrate deploy
npm run dev                     # http://localhost:3006
```

To point a program at it: `MonitoringApp.exe --license-server http://localhost:3006`
(or set `BARPI_LICENSE_SERVER`).

## Environment

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL. On Railway: `${{Postgres.DATABASE_URL}}?schema=licensing`, its own schema in the barpi database |
| `PLATFORM_ADMIN_PASSWORD` | The admin password |
| `PLATFORM_SESSION_SECRET` | Signs the admin cookie (16+ chars) |
| `LICENSE_SIGNING_SECRET` | Signs activation tokens (16+ chars); changing it makes every computer activate again |
| `PUBLIC_URL` | `https://license.oncue.cy` |
| `LICENSE_CHECK_INTERVAL` | Optional; seconds between check-ins (default 300) |
| `LICENSE_FILE_PRIVATE_KEY` | RSA-2048 private key (base64 PKCS#8 DER) that signs offline licence files; from `deploy/keygen.mjs` |
| `DOWNLOADS_DIR` | Where uploaded builds are stored (`/data/downloads` on the Railway volume; `./data/downloads` locally) |

## Deployment (Railway + Cloudflare)

The platform runs in its **own Railway project, `licensing`** (id `8fefc010-a153-4a9a-8a4c-be4df23a00a4`),
separate from the newsroom app: a `Postgres` service and a `player` service built from this
repository with root directory `/platform`, start command `npm run start:prod` (applies the
migrations, then starts Next) and health check `/api/health`. Railway no longer accepts
`railway.json` config-as-code, so those three settings live on the service itself; the
`railway.json` here is kept only as documentation of them.

Custom domain `license.oncue.cy` → Cloudflare zone `oncue.cy`, two records, both required:

| Type | Name | Value | Proxy |
| --- | --- | --- | --- |
| CNAME | `license` | the target Railway shows for the domain (`*.up.railway.app`) | DNS only (grey cloud) |
| TXT | `_railway-verify.license` | the `railway-verify=…` token Railway shows | n/a |

The certificate issues a few minutes after both records are live (see the main README's
"Cloudflare DNS" section for why the TXT matters). The target and token change if the
service is ever recreated: `railway domain status license.oncue.cy --service player`.

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
  --variables PUBLIC_URL=https://license.oncue.cy --variables PLATFORM_ADMIN_PASSWORD=… \
  --variables PLATFORM_SESSION_SECRET=… --variables LICENSE_SIGNING_SECRET=…
railway api --var serviceId=… --var environmentId=… --var input='{"rootDirectory":"/platform","startCommand":"npm run start:prod","healthcheckPath":"/api/health"}' \
  'mutation($serviceId: String!, $environmentId: String!, $input: ServiceInstanceUpdateInput!) { serviceInstanceUpdate(serviceId: $serviceId, environmentId: $environmentId, input: $input) }'
railway service source connect --repo giannakkas/barpi --branch main --service player
railway domain license.oncue.cy --service player      # prints the CNAME target and the TXT token
```

The service deploys from branch `claude/barpi-monitor` until that branch is merged; then
switch it to `main` (`railway service source connect … --branch main`). Variables: see
"Environment" above; do **not** set `NODE_ENV`.
