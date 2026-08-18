# End-to-end tests

The Milestone 4 Playwright suite exercises the compiled application through
Caddy at a mobile viewport. It covers registration, provisional login, explicit
mocked geolocation, nested Taub resolution, session/visit restoration, Leave,
logout, denied permission, low accuracy, unknown and ambiguous results, rapid
click suppression, offline behavior, SPA fallback, security and cache headers,
request-size enforcement, WebSocket upgrades, and service-worker cache
isolation.

Run it with an isolated Compose project so test-mode routes and data never
share state with local development:

```sh
docker compose --env-file .env -p placepulse-e2e-test \
  -f deploy/compose.yml \
  -f deploy/compose.test.yml \
  run --rm --build e2e
```
