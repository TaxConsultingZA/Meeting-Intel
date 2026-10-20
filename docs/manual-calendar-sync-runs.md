# Explicit calendar sync: durable confirmation

Release audit (2026-10-20): the existing Railway API deployment
`6d9ef821-68ea-427f-b111-99d17231629b` already contains the isolated sync-run
implementation. A read-only query of `alembic_version` confirmed revision
`40c8e12a9b71`; no migration was rerun and no business rows were read.
This Git release brings the approved API and latest Dashboard UI into the same
pushed source version. It excludes BusinessAI and unrelated local work.

## Established evidence and limits

The two existing Railway requests `FVxN04YJS3qHDEAK2prcFg` and
`0GuOGP-cTVCxIQnjlt7tkg` ended at the edge with 499 after 29.779 and 30.449
seconds. The frontend at that time had a 30-second AbortController deadline.
The logs do not identify which backend phase was waiting, whether the timer
versus another client disconnect ended these particular requests, or whether
any user transaction committed.

The installed Uvicorn protocol drops sends when disconnected without cancelling
the normal application coroutine, and skips the response/access log. The
offline regression reproduces calendar commits after such a disconnect. The
legacy sync commits calendar rows per user and commits the status separately.
Consequently, missing POST completion logs do not prove failure, cancellation,
or absence of partial writes. Do not resubmit these historical operations on
this evidence alone. They have no retroactively recoverable run ledger.

Synchronous Entra key refresh and MSAL token acquisition were also called from
the event loop. They now run off-thread for authentication and calendar reads.
That is a proven responsiveness defect, not proof of these incidents' wait point.

## Minimal schema and API change

Migration source `40c8e12a9b71` adds only `calendar_sync_runs`, after existing
head `2f7b9c1d4e60`. It stores UUIDs, state, timestamps, safe error categories and
aggregate counts. It neither changes nor backfills existing calendars/users,
stores no calendar content or tokens, and performs no seed or startup DDL.
The requester is an internal user UUID, not an email address. A unique nullable
active slot permits only one queued/running/unresolved operation across API
instances; unknown outcomes retain that slot.

`POST /calendar/sync` now requires a browser-generated `request_id` UUID and
returns 202 with the durable run. Repeating the same ID returns that operation,
never starts it again. An active operation takes precedence over a new ID.
`GET /calendar/sync?run_id=...` reads a specific operation; omitting the ID reads
the active operation or latest result. Both require an existing subscribed admin.
Legacy caller-supplied targets remain forbidden. Legacy synchronous operations
are also checked with the existing PostgreSQL advisory-lock key; new ownership
uses a transaction-scoped lock compatible with transaction pooling.

Only after the operation is durable does the API register a lifespan-owned task.
The task's heartbeat and sync subtasks are awaited/cancelled by that owner.
Client disconnect does not cancel that owner. API shutdown cancels and joins it,
and records unknown when possible. Startup never resumes or retries operations.
A heartbeat older than 60 seconds is displayed as unknown; it is not permission
to start another operation. A run has a 15-minute resource ceiling, and each
user's Microsoft read has a 90-second ceiling. Reaching a run ceiling or an
ambiguous infrastructure/commit failure stops work and blocks automatic retry.
These bounds do not extend the browser's HTTP deadline: acceptance/status HTTP
requests have a separate 20-second server ceiling.

Only existing subscribed users with an Entra identity link are candidates. The
subscription is rechecked and locked before each Microsoft read. The identity
link is not a new Graph grant; reads use existing app-only permission and fail
safely if Microsoft refuses it. No Worker, recording, mail, AI or scheduled sync
is invoked. A user's event writes, status and run counters commit in one
transaction. Confirmed previous users remain visible in the counters after a
later interruption. Infrastructure failure is not mislabelled a Graph failure.

The browser stores only the pending UUID in localStorage before submitting. A
lost response, refresh, polling failure or unknown outcome results only in
status reads, not POST retries. Once a terminal result is observed, that UUID
is cleared. The Dashboard blocks another sync while acceptance/outcome is
uncertain and offers a read-only Check sync status action. Unknown displays the
last confirmed saved counts and requires investigation. Do not manually clear
an active slot or pending ID to bypass this protection.

## Release controls

1. Establish that the historical operations are no longer running and reconcile
   their outcomes/possible partial writes through a separately authorized review.
   Current edge/access logs alone cannot do this.
2. Require schema revision `40c8e12a9b71` before deployment. It was confirmed
   present during this audit; do not rerun the migration.
3. Release API and matching frontend together. An old frontend without
   `request_id` receives validation failure rather than accidentally starting a
   run; a new frontend pointed at the old API keeps status unconfirmed. Expect
   manual sync to be unavailable during this brief contract cutover.
4. Keep scheduled sync, mail and recording processing disabled; keep Worker
   offline. Verify health and content-free phase/run logs. Logs now join edge
   request ID (when supplied), diagnostic UUID, run UUID, phases and safe counts.
5. Only after the historical safety gate is satisfied, submit at most one real
   browser operation, then observe that ID through GET status and terminal logs.

Unknown after an API crash deliberately requires operator reconciliation instead
of automatic resume: earlier users may already have committed. Releasing that
block is a separate, explicitly reviewed data operation, not a retry button.

## Files changed for this implementation

- `app/api/calendar.py`: accept/read endpoints and content-free request-phase diagnostics.
- `app/api/deps.py`: off-thread synchronous signing-key validation.
- `app/graph/client.py`: off-thread calendar token acquisition.
- `app/main.py`: manual-operation lifecycle ownership; retain the earlier no-DDL startup fix.
- `app/models.py`: operation metadata model and unique active slot.
- `app/services/calendar_runs.py`: durable ownership, idempotency, heartbeat and safe outcomes.
- `app/services/calendar_sync.py`: eligible-user flow and transactional progress.
- `app/services/sync_state.py`: optional caller-owned transaction.
- `app/workers/sync_microsoft.py`: optional caller-owned calendar commit; no Worker startup change.
- `alembic/versions/40c8e12a9b71_calendar_sync_runs.py`: additive migration source only.
- `frontend/src/lib/api.ts`: one submission, UUID retention and read-only observation.
- `frontend/src/app/dashboard-client.tsx`: recover state, display results and block unknown retries;
  preserve the previous layout work.
- `app/tests/test_calendar_runs.py`: local transaction and disconnected-request regressions.
- `app/tests/test_manual_calendar_sync.py`: updated API contract and authorization tests.
- `frontend/src/lib/__tests__/api.test.ts`: polling, lost confirmation and reload safety tests.
- `frontend/src/app/__tests__/dashboard-layout.test.tsx`: recovery and unknown-state controls.
- `docs/manual-calendar-sync-runs.md`: evidence, schema impact, limits and release requirements.

All unrelated pre-existing local changes remain in place and are outside this
release. No real calendar submission is part of release verification. The two
historical requests remain unconfirmed; loaded meetings and old sync history do
not establish their outcome. Public-page load times and backend/database slow
points remain unmeasured; mock tests do not prove overall speed improvement.
