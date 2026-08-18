# PlacePulse frontend

The frontend is a strict TypeScript React PWA built by Vite and served only as
compiled static files from the `web` Caddy container. The browser uses
same-origin `/api` and `/ws` routes; it never connects directly to FastAPI or
infrastructure services.

The service worker caches only the public application shell and hashed static
assets. API, WebSocket, location, message, and media requests are always kept
out of its caches. Updates wait for an explicit user action before activating.

The primary mobile flow restores a session, registers or signs in, explains the
provisional unverified state, and requests one high-accuracy geolocation fix
only after the user presses the location button. It represents denied,
unavailable, timeout, low-accuracy, ambiguous, unknown, resolved, and offline
states. Visits end only through a new place resolution, Leave, or logout; there
is no hidden-tab, unload-beacon, or background-location behavior.

Local host tooling is optional. When Node.js is available, the focused checks
are:

```sh
npm ci
npm run check
npm run test
npm run build
```

The supported clean-checkout workflow remains Docker Compose from the
repository root.

After configuring `.env`, start the stack with `docker compose up -d --build`.
Use `http://localhost:8080` for normal local development or
`https://localhost:8443` when testing a secure context. Caddy generates a local
development certificate; browsers may warn until its local authority is trusted.
Geolocation requires a secure browser context and explicit permission. Use the
HTTPS endpoint for behavior closest to Azure.
