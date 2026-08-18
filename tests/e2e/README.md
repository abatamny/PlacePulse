# End-to-end tests

The Milestone 3 Playwright suite exercises the compiled application through
Caddy. It covers the React-to-API route, SPA fallback, security and cache
headers, request-size enforcement, WebSocket upgrades, service-worker cache
isolation, offline shell behavior, and narrow-screen layout.

Run it with an isolated Compose project so test-mode routes and data never
share state with local development:

```sh
docker compose -p placepulse-e2e-test \
  -f deploy/compose.yml \
  -f deploy/compose.test.yml \
  run --rm e2e
```
