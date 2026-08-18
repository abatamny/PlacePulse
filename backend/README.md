# Backend

The backend is a Python 3.13 async FastAPI application packaged with `uv`. The
single command-neutral image is used by `api`, `bootstrap`, and `test-runner`;
Compose supplies each command explicitly. A worker is not implemented before
Milestone 6.

The supported workflow is through Docker Compose from the repository root. Host
Python and host `uv` are optional and are not part of the clean-checkout path.

- `src/placepulse/api/` contains the HTTP application and health endpoints.
- `src/placepulse/bootstrap.py` runs transactional, insert-only cold seeding.
- `migrations/` contains the reviewed Alembic history.
- `tests/unit/` and `tests/contracts/` require no service daemon.
- `tests/integration/` uses real PostgreSQL/PostGIS and Redis from Compose.
