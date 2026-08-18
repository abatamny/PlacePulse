# Test layout

- Backend unit, contract, integration, and security tests live under
  `backend/tests/`.
- Browser system tests will live under `tests/e2e/` from Milestone 3 onward.
- Load and fairness tests will live under `tests/load/` when the worker and
  real-time features exist.

All service-backed tests use an isolated Compose project name and must not share
database, Redis, object, account, or volume state with local development.

On a Windows Docker host, `system/verify-persistence.ps1` checks that the seeded
PostgreSQL campus row and a namespaced Redis key survive a normal restart. It
accepts only project names ending in `-test`; pass `-Cleanup` to remove that
explicitly named disposable project's containers and volumes after the check.
