# Backend

The backend is a Python 3.13 async FastAPI application packaged with `uv`. The
single command-neutral image is used by `api`, `bootstrap`, and `test-runner`;
Compose supplies each command explicitly. A worker is not implemented before
Milestone 6.

The supported workflow is through Docker Compose from the repository root. Host
Python and host `uv` are optional and are not part of the clean-checkout path.

- `src/placepulse/api/` contains the HTTP application and health endpoints.
- `src/placepulse/auth.py` owns normalized account lookup, Redis sessions, and
  fixed-window rate limits; `security.py` centralizes Argon2id and opaque tokens.
- `src/placepulse/location.py` performs uncertainty-aware PostGIS resolution and
  transactional visit transitions without retaining raw coordinates.
- `src/placepulse/verification.py` defines the injectable provider boundary; the
  normal adapter is intentionally disabled and no verification routes exist yet.
- `src/placepulse/bootstrap.py` runs transactional, insert-only cold seeding.
- `migrations/` contains the reviewed Alembic history.
- `tests/unit/` and `tests/contracts/` require no service daemon.
- `tests/integration/` uses real PostgreSQL/PostGIS and Redis from Compose.

The Milestone 4 routes are `/auth/session`, `/auth/register`, `/auth/login`,
`/auth/logout`, `/location/current`, `/location/resolve`, and `/location/leave`.
Caddy exposes them under same-origin `/api/*`. Feature responses are typed in
OpenAPI, use the shared envelope, and are never cacheable.

`email-validator` is the only new production package in this milestone. It is
used at the API boundary for standards-based address syntax and normalization;
delivery checks remain the responsibility of the future verification provider.
