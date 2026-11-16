# Hosting Finboard for several people (server mode)

By default Finboard runs in **local mode**: one user, no sign-in, reachable only from the
machine it runs on ([README › Install](../README.md#install)). **Server mode** adds sign-in, so
a household or a small group can share one server while each person sees only their own data.

Read this page before putting a Finboard on a network. It holds people's bank statements.

## What server mode gives you

- Each person signs in with a username and password. Passwords are stored as argon2id hashes.
- Sessions live on the server (Redis). The browser holds only a random id in a cookie that
  scripts can't read (`HttpOnly`, `SameSite=Strict`, and `Secure` over https).
- Every person's data is separated in three layers: the queries, the foreign keys, and
  Postgres row-level security ([ADR-0025](adr/0025-tenant-isolation-rls.md)). The test suite
  that proves "user B never sees user A's data" runs against real sign-in sessions.
- Limits per person: requests per minute, uploads per hour, and stored statements (5 GB).

What it does **not** give you: password reset by email, two-factor sign-in, or an admin
screen. Accounts are managed from the command line (below). Decisions and their reasons are in
[ADR-0041](adr/0041-server-mode-as-built.md).

## 1. Start it

You need the stack from the README, a domain name pointing at the machine, and a TLS reverse
proxy on that machine (step 2).

```sh
docker compose -f deploy/compose.yaml run --rm init        # once, as in local mode
```

Add to `deploy/.env`:

```sh
FINBOARD_PUBLIC_URL=https://finboard.example.com    # the address people will open
```

Then start it with the server override, and create the first account:

```sh
docker compose -f deploy/compose.yaml -f deploy/compose.server.yaml up -d
docker compose -f deploy/compose.yaml -f deploy/compose.server.yaml exec api finboard create-user alice
```

Use both `-f` files for every later command too (`pull`, `up`, `exec`, `down`).

Finboard refuses to start in server mode without `FINBOARD_PUBLIC_URL`, and refuses a plain
`http://` address unless it is this machine (`127.0.0.1` or `localhost`): passwords must not
cross a network unencrypted.

## 2. Put a TLS proxy in front

The app listens on `127.0.0.1:8765` only. A reverse proxy on the same machine terminates TLS
and forwards to it. The proxy must pass the `Host` header through unchanged, because Finboard
checks it against `FINBOARD_PUBLIC_URL`.

[Caddy](https://caddyserver.com/) gets and renews the certificate by itself:

```
finboard.example.com {
    reverse_proxy 127.0.0.1:8765
    request_body {
        max_size 25MB
    }
}
```

nginx, with a certificate you obtained (for example with certbot):

```nginx
server {
    listen 443 ssl;
    server_name finboard.example.com;
    ssl_certificate     /etc/letsencrypt/live/finboard.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/finboard.example.com/privkey.pem;
    client_max_body_size 25m;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

Do not publish port 8765 itself, and do not change the compose file to bind it to `0.0.0.0`.

## 3. Accounts

| Task | Command (after `docker compose -f deploy/compose.yaml -f deploy/compose.server.yaml exec api`) |
|---|---|
| Create an account | `finboard create-user alice --display-name "Alice"` |
| Reset a password (signs that person out everywhere) | `finboard set-password alice` |

Both ask for the password without showing it. In a script, pipe it in and add
`--password-stdin`.

**Sign-up is closed by default**: only you create accounts. `FINBOARD_SIGNUP=open` in
`deploy/.env` lets anyone who can reach the server create one from the sign-in page. Open it
only if that is what you want, and consider closing it again once everyone has joined.

People change their own password under Settings › Preferences. A password is at least 10
characters; there are no rules about symbols.

**Moving from local mode.** Your existing data belongs to a user called `local`, which has no
password. Give it one and sign in as `local`:

```sh
docker compose -f deploy/compose.yaml -f deploy/compose.server.yaml exec api finboard set-password local
```

## 4. Settings

All go in `deploy/.env`.

| Variable | Default | Meaning |
|---|---|---|
| `FINBOARD_PUBLIC_URL` | (required) | The https address people open |
| `FINBOARD_SIGNUP` | `closed` | `open` shows "Create an account" on the sign-in page |
| `FINBOARD_STORAGE_QUOTA_BYTES` | `5368709120` (5 GB) | Stored statements per person; `0` for no limit |
| `FINBOARD_RATE_LIMIT_PER_MINUTE` | `600` | Requests per person per minute; `0` for no limit |
| `FINBOARD_API_WORKERS` | `2` | API processes |
| `FINBOARD_DB_POOL_SIZE` / `FINBOARD_DB_MAX_OVERFLOW` | `8` / `4` | Database connections per API process |
| `FINBOARD_FORWARDED_ALLOW_IPS` | `*` | Proxies whose `X-Forwarded-For` is trusted. `*` is safe here only because the port is bound to loopback |

Sign-in protections that aren't in the compose file can be set the same way if you add them
to `deploy/compose.server.yaml`: 5 wrong passwords lock an account's sign-in for 15 minutes
(`FINBOARD_LOGIN_MAX_FAILURES`, `FINBOARD_LOGIN_WINDOW_SECONDS`); a session ends after 7 days
unused and at most 30 days old (`FINBOARD_SESSION_IDLE_DAYS`, `FINBOARD_SESSION_MAX_DAYS`).

### Sizing

One API process serves roughly 25 to 130 requests a second, depending on the machine. Each
keeps its own database connections, and Postgres accepts 100 in total, so keep

    API processes × (pool size + overflow) + 2 per worker process  <  100

With the defaults that allows up to 7 API processes. Beyond that, put PgBouncer in front of
Postgres. Measured numbers are in [BUILD_NOTES › M8](BUILD_NOTES.md#m8-multi-user-login).

## 5. Statements in S3 (optional)

By default uploaded statements stay in the `finboard_data` Docker volume. To keep them in an
S3-compatible store instead, use the `-s3` image and set:

```sh
FINBOARD_IMAGE=ghcr.io/kapilsharma/finboard:latest-s3
FINBOARD_BLOB_BACKEND=s3
FINBOARD_S3_BUCKET=my-finboard-bucket
FINBOARD_S3_REGION=ap-south-1
FINBOARD_S3_ACCESS_KEY_ID=...
FINBOARD_S3_SECRET_ACCESS_KEY=...
# FINBOARD_S3_ENDPOINT_URL=https://...   for a store that isn't AWS
# FINBOARD_S3_PREFIX=finboard            to share a bucket
```

Keep the bucket private and turn on its encryption at rest. Statements are stored exactly as
uploaded, so a password-protected PDF stays password-protected. Switching backends does not
move existing files.

## 6. Backups

- **Database:** `docker compose ... exec db pg_dump -U postgres -Fc finboard > finboard.dump`.
  This file contains everyone's transactions in plain form. Encrypt it.
- **Statements:** the `finboard_data` volume, or the bucket.
- **`deploy/.env`:** without it the database passwords are gone.
- Each person can also export their own data under Settings › Data.

## 7. What to know about the risks

- Anyone with shell access to the server, the database or the backups can read everyone's
  data. Row-level security separates users from each other, not from the operator.
- Finboard has not had an independent security review. For anything beyond people you know,
  put it behind a VPN or an authenticating proxy as well.
- Redis holds the sessions. Restarting it signs everyone out, which is harmless.
- The optional AI features are per server and per person, exactly as in local mode
  ([README › AI features](../README.md#ai-features-optional-off-by-default)).
