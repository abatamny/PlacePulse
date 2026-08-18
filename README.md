# PlacePulse

PlacePulse is a mobile-first, place-centered social application. Milestones 0–2
are complete. They provide the contracts, PostgreSQL/PostGIS and Redis
infrastructure, shared FastAPI backend image, health endpoints, migrations, and
deterministic cold seed.
There is no browser-facing application or public URL until Milestone 3.

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

The standard local and Azure graphs publish no ports in Milestones 0–2. Use the
debug overlay only for localhost diagnostics:

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

With the debug overlay enabled:

```sh
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
```

## Tests

Run deterministic backend tests through the test-only Compose overlay with an
isolated project name:

```sh
docker compose -p placepulse-test \
  -f deploy/compose.yml \
  -f deploy/compose.test.yml \
  run --rm test-runner
```

The test runner first applies Ruff and strict mypy gates, then covers contracts,
settings, health behavior, request IDs, logging redaction, migrations, real
PostgreSQL/PostGIS and Redis connectivity, spatial containment, and seed
idempotency. Test project volumes must never be shared with local development.

On PowerShell, the isolated normal-restart persistence check is:

```powershell
.\tests\system\verify-persistence.ps1 -ProjectName placepulse-persistence-test -Cleanup
```

## Seed data

The cold seed is insert-only and uses deterministic UUIDs. It creates one
Technion campus place, three fictional `.invalid` users, two campus posts, three
comments, and one seed-registry row. Rerunning bootstrap does not duplicate or
overwrite those rows.

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
frontend/       Milestone 3 placeholder
tests/          Future browser and load-test layout
```

## Current scope boundaries

There is no authentication or social-content API yet. WebSockets, foreground
presence, the worker and fair queue, media handling, MinIO, and local AI services
remain assigned to their later milestones. The shared backend image deliberately
has no default worker or Uvicorn command; Compose supplies explicit commands for
`api`, `bootstrap`, and `test-runner`.
