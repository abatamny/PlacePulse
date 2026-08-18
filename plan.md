# PlacePulse Development Plan

## Purpose

This document defines the high-level implementation order for PlacePulse, the target Docker architecture, port allocation, service isolation, persistent storage, startup dependencies, testing strategy, and Azure deployment path.

The plan is based on the PlacePulse project proposal, the project-wide course guidelines, and Abed's project-specific guidelines.

## Implementation Status

| Milestone | Status | Verified |
| --- | --- | --- |
| 0 - Repository Foundation and Contracts | Complete | 2026-08-18 |
| 1 - PostgreSQL/PostGIS and Redis | Complete | 2026-08-18 |
| 2 - Backend Image, API, and Bootstrap | Complete | 2026-08-18 |
| 3 - Web Container and React Shell | Complete | 2026-08-18 |
| 4 - First Complete Location Slice | Complete | 2026-08-18 |
| 4.5 - Signed-In Radar and Place Interaction | Planned | - |

Milestone 4 passed its clean Docker Compose workflow on 2026-08-18: migrations
and seeds ran from empty volumes, all backend and integration checks passed,
the compiled web/API stack became healthy, logs contained no sensitive
location or authentication values, and the isolated mobile Playwright suite
passed through Caddy.

Milestone 4.5 is the next planned milestone. It separates the authenticated
application from the public account-entry experience and introduces the first
small, persisted, text-only place interaction slice without pulling forward
foreground presence, live WebSocket delivery, media, reactions, or AI.

## Core Architecture Decisions

- Development and Azure production must provide the same features and use the same runtime service graph.
- Docker Compose is the canonical way to run PlacePulse.
- Only the `web` container is exposed to clients.
- The API, databases, queues, object storage, workers, and AI services remain private inside Docker networks.
- PostgreSQL with PostGIS stores persistent relational and geographic data.
- Redis provides presence state, fair job queues, Pub/Sub, rate limiting, caching, and distributed coordination.
- MinIO stores images and videos outside the relational database.
- Long-running AI and media work is executed asynchronously by the worker.
- Ollama runs the pinned Qwen3.5 model.
- Qwen3Guard runs as a separate internal moderation service.
- Model names, versions, prompts, and structured-output schemas are pinned across environments.
- Mocks and simulated services are allowed only in the test configuration, never in normal development.

## Target Runtime Containers

Eight containers remain running in both local development and Azure production.

| Container | Responsibility |
| --- | --- |
| `web` | Serves the compiled React TypeScript PWA through Caddy, terminates TLS, applies security headers and request-body limits, and proxies API and WebSocket traffic. It is the only publicly exposed container. |
| `api` | Runs FastAPI and implements authentication, users, place resolution, visits, ranks, KNOCK, DIG, forums, comments, reactions, direct messages, notifications, uploads, REST endpoints, and WebSockets. It submits expensive jobs to Redis rather than executing them inside HTTP requests. |
| `worker` | Processes fair per-user queues, moderation tasks, place-layer selection, images, video frames, FFmpeg jobs, DIG expiration, Explore selection, scheduled cleanup, and notification events. It uses the same backend image as `api`, with a different startup command. |
| `postgres` | Runs PostgreSQL with PostGIS and stores users, password hashes, places and polygons, visits, ranks, social content, messages, notifications, moderation records, DIG metadata, Explore memories, and media metadata. |
| `redis` | Stores foreground presence, per-user job queues, job results, Pub/Sub events, WebSocket notification events, rate-limit counters, temporary state, caches, and distributed locks. Persistence is enabled for jobs that must survive restarts. |
| `minio` | Provides private S3-compatible storage for images, videos, thumbnails, and extracted frames. Database rows contain object identifiers and metadata rather than media blobs. |
| `ollama` | Serves the pinned Qwen3.5 model for nested-place interpretation, contextual classification, image/video-frame inspection, and Explore-event analysis. |
| `qwen-guard` | Serves the pinned Qwen3Guard-Gen model for text safety classification and jailbreak resistance across posts, comments, KNOCK messages, direct messages, and metadata. |

## Startup and Utility Containers

These containers run when needed and then exit.

| Container | Responsibility |
| --- | --- |
| `bootstrap` | Runs Alembic migrations, enables PostGIS, imports initial geographic data, and performs idempotent cold seeding with fake users, posts, and comments. |
| `model-init` | Waits for the model services, downloads or verifies the pinned model artifacts, and prepares persistent model volumes. |

## Test-Only Containers

These services are enabled only through the test Compose configuration.

| Container | Responsibility |
| --- | --- |
| `test-runner` | Runs unit, integration, authentication, authorization, input-validation, rate-limiting, and security tests. |
| `e2e` | Runs Playwright system tests covering browser geolocation, complete user flows, uploads, WebSockets, notifications, and recovery behavior. |
| `load-test` | Runs k6 or Locust stress tests for concurrent users, spam requests, WebSocket traffic, fair-queue behavior, and oversized uploads. |

## Docker Images

We do not maintain a different custom image for every container.

| Image | Used by |
| --- | --- |
| `placepulse-web` | `web` |
| `placepulse-backend` | `api`, `worker`, `bootstrap`, and `test-runner` |
| `placepulse-qwen-guard` | `qwen-guard` |
| Pinned standard images | PostgreSQL/PostGIS, Redis, MinIO, Ollama, Playwright, and the load-test tool |

## Compose Organization

```text
deploy/
├── compose.yml          # Canonical services, networks, health checks, and volumes
├── compose.local.yml    # Local host ports, GPU access, certificates, and watch settings
├── compose.azure.yml    # Azure domain, TLS, secrets, restart policies, and resource limits
├── compose.test.yml     # Test runners and isolated test data
└── compose.debug.yml    # Optional localhost-only diagnostic ports
```

The canonical `compose.yml` defines the application graph. Environment overlays may change host bindings, domains, secrets, certificates, volume paths, logging, and resource limits, but they must not remove features.

## Port Allocation

Only `web` publishes host ports. The remaining ports are reachable only by authorized containers on Docker networks.

| Container | Internal port | Local host | Azure host |
| --- | ---: | ---: | ---: |
| `web` HTTP | `80` | `8080` | `80` |
| `web` HTTPS | `443` | `8443` | `443` |
| `api` | `8000` | Not published | Not published |
| `postgres` | `5432` | Not published | Not published |
| `redis` | `6379` | Not published | Not published |
| `minio` S3 API | `9000` | Not published | Not published |
| `minio` console | `9001` | Not published | Not published |
| `ollama` | `11434` | Not published | Not published |
| `qwen-guard` | `8001` | Not published | Not published |
| `worker` | None | None | None |
| Startup and test containers | None | None | None |

The normal local URL is `http://localhost:8080`. A trusted local HTTPS configuration is required when testing geolocation from a physical phone over the LAN.

Optional diagnostic ports may be defined in `compose.debug.yml` and bound only to `127.0.0.1`. They must never be enabled by default or published on Azure.

## Docker Networks

| Network | Members | Purpose |
| --- | --- | --- |
| `ingress` | `web` | Allows Docker to publish only Caddy's HTTP and HTTPS ports to the host. |
| `edge` | `web`, `api` | Internal network allowing Caddy to proxy requests to FastAPI. |
| `core` | `api`, `worker`, `postgres`, `redis`, `minio`, `bootstrap` | Carries application data, queues, presence, and storage traffic. |
| `ai` | `worker`, `ollama`, `qwen-guard`, `model-init` | Isolates the local AI services from clients and the web tier. |

The intended access rules are:

- The browser communicates only with `web`.
- `web` communicates with `api`, not with databases or AI services.
- `api` communicates with PostgreSQL, Redis, and MinIO.
- `api` submits AI work to Redis rather than calling models directly.
- `worker` communicates with Redis, PostgreSQL, MinIO, Ollama, and QwenGuard.
- Ollama and QwenGuard are never exposed to clients.

## Persistent Volumes

| Volume | Contents |
| --- | --- |
| `postgres_data` | Relational and geographic application data |
| `redis_data` | Persistent job queues and recoverable temporary state |
| `minio_data` | Uploaded images, videos, thumbnails, and frames |
| `ollama_models` | Pinned Qwen3.5 model artifacts |
| `qwen_guard_models` | Pinned QwenGuard model artifacts and cache |
| `caddy_data` | Certificates and Caddy state |
| `caddy_config` | Caddy runtime configuration |

## Milestone 0 - Repository Foundation and Contracts

**Status: Complete (verified 2026-08-18).**

Establish the project structure and cross-service contracts before implementing features.

### Work

- Define frontend, backend, deployment, and test directories.
- Define environment-variable names and add a safe `.env.example`.
- Create the initial Compose files, networks, and volumes.
- Define API response and error conventions.
- Define REST and WebSocket event contracts.
- Define the queue-job envelope, job states, retry rules, and idempotency keys.
- Define media object keys and metadata.
- Define AI request and structured-response schemas.
- Establish health-check conventions.
- Establish logging conventions and correlation IDs.
- Add initial README instructions.

### Exit criteria

- [x] `docker compose config` succeeds.
- [x] The documented directory and configuration structure exists.
- [x] No secrets are committed.
- [x] Cross-service contracts are documented and testable.

## Milestone 1 - PostgreSQL/PostGIS and Redis

**Status: Complete (verified 2026-08-18).**

Build the core persistent-data and coordination infrastructure.

### Work

- Add the pinned PostgreSQL/PostGIS image.
- Add the pinned Redis image with persistence enabled.
- Add health checks for both services.
- Add named volumes.
- Verify database and Redis connectivity from a temporary backend command.
- Define the first database migration and confirm PostGIS is enabled.

### Exit criteria

- [x] PostgreSQL and Redis become healthy from a clean start.
- [x] PostGIS spatial types and functions are available.
- [x] Data survives a normal container restart.

## Milestone 2 - Backend Image, API, and Bootstrap

**Status: Complete (verified 2026-08-18).**

Create the shared backend image and the first runnable backend services.

The initial implementation intentionally introduces the minimal user, place,
post, and comment schema needed for deterministic cold seeding. This is database
and seed infrastructure only; social endpoints remain in their later milestones.
The backend image is kept command-agnostic, but the `worker` service and all
queue-processing behavior remain deferred until Milestone 6.

### Work

- Create the Python/FastAPI backend image.
- Run Uvicorn in the `api` container.
- Reuse the backend image for `api`, `bootstrap`, and tests; keep it suitable for
  the worker command that will be added in Milestone 6.
- Add `/health/live` and `/health/ready`.
- Configure PostgreSQL and Redis clients.
- Add Alembic migrations.
- Make `bootstrap` run migrations and idempotent cold seeding.
- Add structured logging and request correlation IDs.

### Exit criteria

- [x] `bootstrap` completes successfully from an empty database.
- [x] Re-running `bootstrap` does not duplicate seeded data.
- [x] API liveness and readiness checks pass.
- [x] API starts only after required infrastructure is ready.

## Milestone 3 - Web Container and React Shell

**Status: Complete (verified 2026-08-18).**

Create the only client-facing container.

### Work

- Create the React, Vite, and TypeScript frontend.
- Add the PWA manifest, icons, and service-worker strategy.
- Build the frontend in a Node build stage.
- Serve only the compiled output from the final Caddy image.
- Proxy `/api/*` and `/ws/*` to `api:8000`.
- Add SPA fallback, security headers, compression, and body-size limits.
- Confirm that no other service publishes host ports.

### Exit criteria

- [x] PlacePulse opens through `http://localhost:8080`.
- [x] React can call the API through Caddy.
- [x] WebSockets pass through Caddy.
- [x] Direct host access to the API, database, storage, and models is unavailable.

## Milestone 4 - First Complete Location Slice

**Status: Complete (verified 2026-08-18).**

Implement the smallest end-to-end version of the central PlacePulse concept.

### Work

- Implement registration and provisional login with Argon2id, Redis sessions,
  CSRF protection, generic login failures, and endpoint-specific rate limits.
- Keep email verification explicitly unverified behind an injectable provider;
  the normal adapter is disabled until a provider is configured.
- Seed the reviewed Taub Computer Science Building polygon as a child of the
  Technion campus using the independent `milestone-4-osm-v1` seed entry.
- Request a one-shot browser coordinate only after an authenticated user action.
- Resolve candidates with boundary-inclusive PostGIS containment and
  geography-based uncertainty distances.
- Use `deepest_confident_containing` as Milestone 4's provisional deterministic
  layer-selection rule: select the deepest place whose full reported accuracy
  radius is contained, fall back to a confident parent, and otherwise return an
  explicit ambiguous, unknown, or low-accuracy result.
- Display the selected place, leaf-to-root hierarchy, reason, and visit time.
- Record visit entry and exit only on explicit resolution transitions, Leave,
  or logout.

### Exit criteria

- A user can register, log in, grant location permission, and see the correct place.
- Nested-place results are deterministic and explainable.
- Location errors do not cause fabricated place results.
- The complete slice has unit, integration, and browser tests.

## Milestone 4.5 - Signed-In Radar and Place Interaction

**Status: Planned.**

Replace the signed-in version of the public login page with a dedicated,
mobile-first application view. The selected physical place remains the
authoritative context: the Radar shows recent text posts for that place, a post
can be opened and authored, and its author can be contacted through a basic
persisted KNOCK thread. This milestone is intentionally non-realtime; it must
not imply that an active visit proves foreground presence.

In this milestone, "nearby" means the user's current server-recorded place. A
Radar item is a visual representation of place activity, not a claim about the
post author's precise direction or distance. Raw coordinates are not stored on
posts, KNOCK threads, or messages and are never returned by these APIs.

### Signed-in experience

- Keep registration and login in the public account-entry experience.
- After login, or when restoring an authenticated session, enter a dedicated
  authenticated application shell instead of leaving the user on the landing
  page with only the location card changed.
- Make `Radar` the default signed-in tab and add an accessible `KNOCKS` tab.
- Keep the current handle, online/offline state, selected place, place
  hierarchy, and explicit `Find`, `Refresh`, `Leave`, and `Sign out` actions
  available without returning to the public page.
- If no visit is active, show an honest location-gated empty state and request
  geolocation only after the user presses the location action.
- Use a mobile-first, full-height layout with touch-sized controls, keyboard
  operation, visible focus, reduced-motion support, and no horizontal overflow.
- Keep private posts, messages, location responses, and authenticated API data
  out of the service-worker cache.

### Radar and posts

- Present recent posts from the exact active place in a radar-inspired visual
  surface with an equivalent accessible list. Do not place posts by invented
  bearings or distances.
- Use the existing seeded forum posts as real initial content; do not add
  hard-coded production mocks.
- Return posts through an authenticated, cursor-paginated API with stable
  ordering, author handle, bounded body preview, and timezone-aware creation
  time.
- Allow a Radar item to open a post detail sheet or screen with a direct link
  that survives refresh and browser navigation.
- Allow an authenticated user with an active visit to create a text-only post
  for the exact server-recorded place. Do not trust a client-supplied place as
  authorization.
- Validate and trim post bodies, enforce the existing 1-to-2,000 character
  bound, apply per-user rate limits, and make rapid duplicate submissions
  idempotent.
- Defer titles, anonymity, comments, reactions, images, videos, and cross-layer
  forum browsing to their existing later milestones.

### KNOCKS

- Let a user start a KNOCK with another post's author from the post detail
  view; do not expose a nearby-user list before foreground presence exists.
- Add persisted KNOCK threads and bounded text messages through a forward
  Alembic migration, with explicit place and originating-post context.
- Show the user's threads and message history in the `KNOCKS` tab with clear
  empty, loading, error, unread, and sent states.
- Authorize both thread participants on every read and write, prevent users
  from KNOCKing themselves, and do not reveal threads through guessable IDs.
- Apply per-user and per-thread rate limits, bounded pagination, idempotent
  sends, and stable error codes.
- Use request/refresh delivery in Milestone 4.5. Foreground recipient discovery,
  WebSocket delivery, reconnect behavior, and notifications remain Milestone 5.

### Content-safety boundary

- Treat post and KNOCK text as untrusted input, never render it as HTML, and
  enforce server-side length, validation, authorization, and spam controls.
- Add explicit moderation-state fields and audit timestamps through a forward
  migration now so Milestone 8 can connect QwenGuard without rewriting content
  history.
- Document the provisional pre-model policy. QwenGuard remains the required
  text-safety and jailbreak gate before the complete social feature set is
  considered release-ready; moderation must not be represented as active
  before that service exists.

### Tests and documentation

- Add unit tests for feed mapping, validation, authorization, pagination,
  idempotency, tab state, and reduced-motion behavior.
- Add integration tests with real PostgreSQL and Redis for place isolation,
  post creation, KNOCK participant access, persistence, rate limits, and
  duplicate requests.
- Extend the mobile Playwright flow through Caddy to cover login-to-Radar
  transition, session restoration, location gating, seeded posts, post detail,
  post creation, KNOCK creation/history, refresh delivery, offline behavior,
  direct-route authorization, Leave, and logout.
- Update the root and frontend READMEs with the signed-in navigation, endpoint
  contracts, current moderation boundary, and manual test flow.

### Exit criteria

- A successful login and an authenticated session restore open the signed-in
  application shell rather than the public account-entry view.
- A located user can browse the exact current place's persisted Radar posts,
  open a post, and create a text-only post; a user without an active visit
  cannot read or write place content.
- A user can KNOCK a post author, open the resulting thread, send text, and
  retrieve persisted history without any claim of foreground presence or live
  delivery.
- Posts and KNOCK threads are isolated by place and participant authorization,
  and rapid duplicate actions do not create duplicate content.
- The responsive and accessibility checks plus relevant unit, integration,
  security, and browser tests pass through the documented Docker workflow.

## Milestone 5 - Presence and Real-Time Communication

Add foreground presence and live place-based communication.

### Work

- Implement foreground presence heartbeats in Redis.
- Extend explicit visits with history views and rank calculation.
- Implement `VISITOR` and `BELONG` behavior.
- Add authenticated WebSocket connections.
- Upgrade KNOCK threads to foreground-aware routing and live delivery.
- Publish live Radar/forum updates for the persisted Milestone 4.5 posts.
- Implement direct-message delivery and notifications.
- Add reconnect, timeout, and stale-presence cleanup behavior.

### Exit criteria

- Presence disappears after the heartbeat timeout.
- Users in the same place receive events without refreshing.
- Unauthorized users cannot subscribe to restricted events.
- WebSocket reconnect and API restart behavior are tested.

## Milestone 6 - Worker and Fair Job Queue

Implement the asynchronous execution foundation before connecting real models.

### Work

- Define Redis-backed per-user queues.
- Implement atomic fair scheduling across active users.
- Prioritize users who have waited longest while preventing one user from monopolizing workers.
- Implement job states: queued, processing, passed, rejected, failed, and expired.
- Add timeouts, bounded retries, idempotency, cancellation, and dead-letter handling.
- Add worker heartbeat and graceful shutdown.
- Add configurable worker concurrency.
- Use a deterministic processor only in the test configuration.

### Exit criteria

- A user submitting 1,000 jobs cannot indefinitely block a user submitting one job.
- Jobs survive recoverable restarts.
- Duplicate job delivery does not duplicate side effects.
- Stress tests demonstrate fairness and bounded resource usage.

## Milestone 7 - MinIO and Media Pipeline

Add safe image and video handling.

### Work

- Add MinIO and its persistent volume.
- Stream uploads instead of loading entire files into memory.
- Enforce authentication, content type, extension, size, duration, and dimension limits.
- Use random object identifiers rather than user-controlled paths.
- Run FFprobe validation.
- Use FFmpeg to create thumbnails and extract representative video frames.
- Store media metadata and moderation state in PostgreSQL.
- Implement pending, accepted, rejected, and failed upload states.
- Implement cleanup for rejected, abandoned, expired, and orphaned objects.
- Implement DIG expiration after 24 hours.

### Exit criteria

- Valid images and videos can be uploaded without database blobs.
- Oversized, malformed, and unsupported files are rejected safely.
- Interrupted uploads and worker restarts do not leave uncontrolled storage leaks.
- Media is private and cannot be enumerated anonymously.

## Milestone 8 - Ollama and QwenGuard

Connect the real local AI services through the existing fair queue.

### Work

- Add the pinned Ollama image and persistent model volume.
- Add `model-init` for model download and verification.
- Add the separate QwenGuard service.
- Pin Qwen3.5 and QwenGuard model names and versions.
- Require schema-validated structured responses.
- Add inference timeouts, concurrency limits, and bounded retries.
- Use QwenGuard for text-safety and jailbreak classification.
- Replace only Milestone 4's deterministic place-layer selection step with
  Qwen3.5 nested-place intent selection through the worker queue. The model may
  choose only among candidates already verified by PostGIS, and raw coordinates
  are never sent to an LLM.
- Use Qwen3.5 for image/frame inspection and event analysis.
- Treat model output as untrusted data.
- Fail closed when required moderation is unavailable.
- Store moderation evidence, reason codes, and model versions.
- Add a suite of jailbreak, prompt-injection, and unsafe-content tests.

### Exit criteria

- Ordinary local development and Azure use the same real model path.
- AI calls pass only through the queue and worker.
- Invalid or malformed model responses cannot approve content.
- Known simple jailbreaks are rejected by automated tests.

## Milestone 9 - Complete Social Features and Place Memory

Finish the project proposal and the place-specific forum requirements.

### Work

- Complete the separate forum for each physical place, extending Milestone
  4.5's exact-place text feed across the authorized place experience.
- Extend text-only posts with titles, anonymity, images, and videos.
- Add comments with text, images, and videos.
- Add likes and dislikes on posts and comments.
- Add user post history and reaction totals.
- Complete direct messages with text, images, and videos.
- Add live message and reaction notifications.
- Complete moderated KNOCK routing across nested place layers.
- Complete the 24-hour DIG feed.
- Analyze local activity and create permanent Explore memories.
- Add comments and reactions to Explore content.
- Enforce physical-place access rules for place memories.

### Exit criteria

- Every implemented social flow works without a page refresh where live behavior is required.
- All content is isolated by place and permissions.
- Chat and notification history is persistent and retrievable.
- Cold-seeded accounts, posts, and comments appear after a fresh installation.

## Milestone 10 - Testing, Security, and Resilience

Complete the course-required test categories and risk mitigations.

### Work

- Add comprehensive unit tests.
- Add integration tests using real PostgreSQL, Redis, and MinIO containers.
- Add Playwright end-to-end tests.
- Add stress and fairness tests.
- Add authentication, authorization, input-validation, and upload-security tests.
- Test jailbreaking and prompt injection.
- Test invalid coordinates and ambiguous place boundaries.
- Test rapid button presses, duplicate requests, and idempotency.
- Test interrupted uploads and disconnected clients.
- Test PostgreSQL, Redis, worker, model, and API restart behavior.
- Document availability, redundancy, scalability, spam, security, and persistence risks.
- Ensure tests run from a clean machine through Docker.

### Exit criteria

- Unit, integration, system, stress, and security suites pass from documented commands.
- No test-only endpoints or bypasses exist in normal development or production.
- The README maps each feature to its relevant tests.
- Failure scenarios degrade safely rather than crashing the full application.

## Milestone 11 - Azure Deployment and CI/CD

Deploy the same application graph to the course-provided Azure server.

### Work

- Build immutable images tagged with the Git commit SHA.
- Push images to the selected container registry.
- Run automated tests for every relevant commit or pull request.
- Deploy the Azure Compose overlay after tests pass.
- Run `bootstrap` migrations before accepting traffic.
- Configure the course domain and public HTTPS.
- Store production secrets outside Git.
- Add container restart policies and resource limits.
- Run post-deployment health and smoke tests.
- Keep previous image tags available for rollback.
- Document deployment, recovery, backup, and rollback procedures.

### Exit criteria

- The public domain serves PlacePulse over HTTPS.
- Azure uses the same application services, feature paths, model versions, and database migrations as local development.
- A failed test or smoke check prevents or rolls back deployment.
- A clean local machine can still run the complete project through Docker Compose.

## Runtime Startup Order

Startup is controlled through health checks and completion conditions, not fixed sleeps.

1. Start PostgreSQL, Redis, MinIO, Ollama, and QwenGuard.
2. Run `bootstrap` after PostgreSQL is healthy.
3. Run `model-init` after Ollama is healthy.
4. Start `api` after `bootstrap` completes successfully and its dependencies are healthy.
5. Start `worker` after Redis, PostgreSQL, MinIO, `model-init`, and QwenGuard are ready.
6. Start `web` and route client traffic only to a ready API.

## Codex Execution Protocol

Codex should implement one milestone at a time. It must not start a later milestone until the current milestone's exit criteria pass.

For each milestone, Codex should:

1. Inspect the existing repository and preserve unrelated changes.
2. State the milestone scope and identify the files it expects to change.
3. Implement the smallest coherent vertical slice.
4. Add or update tests in the same change.
5. Update README instructions and configuration examples.
6. Build the affected images.
7. Start the stack from a clean state when relevant.
8. Run the relevant unit, integration, system, stress, or security tests.
9. Inspect container health and logs.
10. Summarize changes, validation results, limitations, and the next milestone.

The baseline validation commands are:

```bash
docker compose config
docker compose build
docker compose up -d
docker compose ps
docker compose logs
```

Additional milestone-specific tests must run before the milestone is considered complete.

## Initial Codex Scope

The first implementation task should cover Milestones 0 through 2 only:

- Repository foundation and service contracts.
- Canonical Compose structure, networks, volumes, and health checks.
- PostgreSQL/PostGIS and Redis.
- Shared backend image.
- FastAPI health endpoints.
- Alembic migrations.
- Idempotent cold seeding.

Frontend features, media processing, and AI integration should not begin until this foundation starts reliably from a clean checkout.
