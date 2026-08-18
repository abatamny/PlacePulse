# PlacePulse cross-service contracts

The JSON files in `v1/` use JSON Schema 2020-12 and are the language-neutral
contract for future HTTP, WebSocket, queue, media, and AI integrations. Contract
examples are validated by `backend/tests/contracts/test_contract_examples.py`.

## HTTP

Future REST endpoints use `/api/v1`. Successful feature responses use `data`,
`meta`, and a UUID `request_id`. Failures use a stable machine-readable
error code and never expose stack traces, dependency hostnames, SQL, prompts, or
secrets. Health endpoints are deliberately smaller and are documented in the
root and backend READMEs.

## WebSocket

Future WebSocket connections use `/ws/v1`. Every command or event carries a
schema version, UUID event ID, event type, UTC timestamp, optional correlation
ID, and an object payload. No WebSocket runtime is implemented in Milestones
0–2.

## Queue jobs

Allowed terminal states are `passed`, `rejected`, `failed`, `cancelled`, and
`expired`. A job moves from `queued` to `processing`; only a transient processing
failure may return it to `queued`. The maximum is three processing attempts with
exponential backoff of 1 then 2 seconds before attempts two and three. Validation and
moderation rejections are permanent. Idempotency keys are scoped to
`(actor_id, job_type, idempotency_key)` and duplicates return the original job.
The queue itself begins in Milestone 6.

## Media and AI

Media keys are server generated and never contain client filenames. AI schemas
carry explicit model and schema versions, treat all inputs and outputs as
untrusted, and do not allow a model to invent factual places. Runtime media and
AI services are outside Milestones 0–2.
