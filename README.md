# PlacePulse

PlacePulse is a mobile-first, place-centered social application. Milestones 0–4
are complete. A user can register, sign in provisionally, request one browser
location fix, resolve reviewed nested PostGIS places, and explicitly enter or
leave a recorded visit through the compiled React PWA and Caddy.

## Prerequisites

- Docker Desktop using Linux containers on AMD64
- Docker Compose 2.20 or newer
- Git

Python and `uv` are installed inside the backend image; neither is required on
the host.

## Configure local secrets

Copy `.env.example` to `.env`, then replace each empty password with a strong,
unique local value. `.env` and `.secrets/` are ignored by Git.

PowerShell:

```powershell
Copy-Item .env.example .env
```

POSIX shell:

```sh
cp .env.example .env
```

The three required secret variables are:

- `PLACEPULSE_POSTGRES_PASSWORD`
- `PLACEPULSE_REDIS_PASSWORD`
- `PLACEPULSE_SEED_PASSWORD`

Compose sources these values from the environment and mounts them into
containers as files under `/run/secrets`. They are never embedded in images.
The seed password is hashed with Argon2id on first insertion; changing it later
does not rotate an existing seed account.

Two non-secret Milestone 4 settings are available:

- `PLACEPULSE_SESSION_TTL_SECONDS` is fixed to 43,200 seconds by default.
- `PLACEPULSE_MAX_LOCATION_ACCURACY_METERS` rejects fixes wider than 100 metres
  by default without changing the active visit.

Runtime profiles are selected by Compose, not by `.env`: the canonical graph is
`local`, the Azure overlay is `azure`, and only the test overlay enables `test`.
This keeps test-only transport probes out of normal local and Azure deployments.

Secret-consuming services keep `no-new-privileges` enabled, and the backend
runs as a dedicated non-root user. Their root filesystems remain writable
because current Docker Desktop cannot inject environment-backed Compose secrets
into a service configured with a read-only root filesystem.

## Compose layout

`deploy/compose.yml` is canonical. The repository-root `compose.yml` includes it
with the local overlay so normal local commands run from the root:

```sh
docker compose config
docker compose build
docker compose up -d
docker compose ps
docker compose logs --no-color
```

The local application is available only through Caddy:

- `http://localhost:8080`
- `https://localhost:8443`

The HTTPS endpoint uses Caddy's local development authority, so a browser may
show a certificate warning until that authority is trusted. The `web` service
is the only service with host port bindings. It uses a dedicated host-facing
`ingress` network and the internal `edge` network to proxy to the API; the API,
PostgreSQL, and Redis stay unpublished.

Use the debug overlay only for direct localhost API diagnostics:

```sh
docker compose -f deploy/compose.yml -f deploy/compose.debug.yml up -d
```

The debug overlay binds the API to `127.0.0.1:8000`; PostgreSQL and Redis remain
private. It must never be enabled on Azure.

## Health and startup

- `GET /health/live` checks only that the API process can serve requests.
- `GET /health/ready` checks PostgreSQL and Redis with bounded timeouts.
- `bootstrap` waits for PostgreSQL, runs `alembic upgrade head`, and applies the
  cold seed in one transaction.
- `api` waits for healthy PostgreSQL and Redis and for `bootstrap` to complete.

Through the normal Caddy route:

```sh
curl http://127.0.0.1:8080/api/health/live
curl http://127.0.0.1:8080/api/health/ready
```

With the debug overlay enabled, the same endpoints are also reachable directly
for diagnostics:

```sh
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
```

## Authentication and location API

All browser calls are same-origin under `/api`, use the
`{data, meta, request_id}` envelope, and return `Cache-Control: no-store`.
FastAPI's generated OpenAPI UI is available through `/api/docs` while the stack
is running.

| Browser endpoint | Purpose |
| --- | --- |
| `GET /api/auth/session` | Restore anonymous/authenticated state and establish CSRF. |
| `POST /api/auth/register` | Create an unverified account without signing in. |
| `POST /api/auth/login` | Create and rotate a 12-hour Redis session. |
| `POST /api/auth/logout` | End the active visit, revoke the session, and clear cookies. |
| `GET /api/location/current` | Restore the active visit without coordinates. |
| `POST /api/location/resolve` | Resolve one latitude/longitude/accuracy fix and transition visits. |
| `POST /api/location/leave` | Idempotently end the active visit. |

Call `GET /api/auth/session` first. Every state-changing request must echo the
returned CSRF token in `X-CSRF-Token`; the browser client does this
automatically. Session tokens are opaque 256-bit values, only their SHA-256
digests are Redis keys, and browser cookies are host-only, SameSite, and
HTTP-only for the session. Secure cookies are required on HTTPS and Azure.

Email verification delivery is deliberately not configured in Milestone 4.
Accounts remain explicitly unverified, API responses report
`pending_provider_configuration`, and provisional login is allowed. There are
no public verification endpoints yet.

Location is requested only after the user presses the location action. Use
`https://localhost:8443` for secure-context testing; browsers also commonly
treat `http://localhost:8080` as trustworthy for local development. Permission
denial, unavailable/timeout, offline, low-accuracy, ambiguous, unknown, and
resolved states are shown without background tracking or unload beacons.

## Tests

Run deterministic backend tests through the test-only Compose overlay with an
isolated project name:

```sh
docker compose --env-file .env -p placepulse-test \
  -f deploy/compose.yml \
  -f deploy/compose.test.yml \
  run --rm --build test-runner
```

The test runner first applies Ruff and strict mypy gates, then covers contracts,
settings, health behavior, request IDs, logging redaction, migrations, auth and
CSRF behavior, real Redis sessions/rate limits, PostGIS uncertainty and nested
selection, visit concurrency, and seed idempotency. It also verifies that the
transport-only WebSocket probe is available exclusively in the test profile.
Test project volumes must never be shared with local development.

Run the compiled frontend system tests through Caddy and Chromium:

```sh
docker compose --env-file .env -p placepulse-e2e-test \
  -f deploy/compose.yml \
  -f deploy/compose.test.yml \
  run --rm --build e2e
```

These tests cover the mobile register/login/location/restore/leave/logout flow,
permission denial, low accuracy, unknown and ambiguous places, rapid clicks,
offline behavior, SPA fallback, gateway security, WebSocket transport, and
service-worker cache isolation.

On PowerShell, the isolated normal-restart persistence check is:

```powershell
.\tests\system\verify-persistence.ps1 -ProjectName placepulse-persistence-test -Cleanup
```

## Seed data

The cold seed is insert-only and uses deterministic UUIDs. The foundation seed
creates the Technion campus, three fictional `.invalid` users, two campus posts,
and three comments. The independent `milestone-4-osm-v1` seed inserts Taub
Computer Science Building as a child only after PostGIS verifies it is valid and
covered by Technion. Rerunning bootstrap does not duplicate or overwrite rows.

The campus boundary is derived from
[OpenStreetMap way 66098525, version 35](https://www.openstreetmap.org/way/66098525/history/35).
Map data © OpenStreetMap contributors and is available under the
[Open Database License](https://www.openstreetmap.org/copyright). The vendored
fixture and its provenance are documented in `data/osm/README.md`.

## Repository map

```text
backend/        FastAPI package, migrations, bootstrap, and backend tests
contracts/      Versioned cross-service JSON Schemas and examples
data/osm/       Reviewed, version-pinned OSM seed fixture and licence notice
deploy/         Canonical Compose graph and environment/test/debug overlays
frontend/       Strict React/Vite PWA, Caddy config, and web image
tests/          Browser system tests plus future load-test layout
```

## Current scope boundaries

Milestone 4 includes HTTP authentication, deterministic place resolution, and
explicit visits. It does not include verification delivery, foreground
presence, authenticated application WebSockets, social-content APIs, the
worker/fair queue, media handling, MinIO, or local AI services. A small echo
endpoint exists only in the test profile to prove the WebSocket transport path.
The shared backend image deliberately has no default worker or Uvicorn command;
Compose supplies explicit commands for `api`, `bootstrap`, and tests.
