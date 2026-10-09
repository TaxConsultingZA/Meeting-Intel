# Architecture

Repository snapshot: 2026-10-09; includes existing uncommitted implementation.
Local development reference; remote hosting references are historical context.

## Frontend

`frontend/` is a Next.js App Router application with React, TypeScript and
Tailwind. `src/app` contains login, dashboard, meeting details, administrator,
audit-log and the locally implemented Action Items routes. Server pages obtain
authentication; client components handle interactive data and edits.
`src/components` provides navigation, notifications, imports, recording jobs and
shared UI. `src/lib/api.ts` attaches bearer tokens and provides request timeout
and safe-error handling; `types.ts` defines response/edit shapes, and time
utilities plus local-date components handle browser timezone display.

## Backend

`app/main.py` assembles FastAPI routers, CORS, error handling and startup tasks.
`app/api` handles review, recordings/jobs, calendar, access/registration,
subscriptions/webhooks, notifications, administrator and action-item endpoints.
`app/services` contains access checks, matching, queue controls, ledger,
reprocessing, synchronization diagnostics and audit logic.
`app/graph` wraps Microsoft authentication, calendar/files and mail operations.
`app/workers` performs discovery/calendar synchronization; `app/queue/worker.py`
consumes durable recording jobs, while `app/pipeline` downloads, transcribes and
extracts meeting content. Discovery/enqueueing and recording consumption are
separate responsibilities.

## Database role

PostgreSQL stores meetings, participants/permissions, action items, recording
jobs and deduplication ledger, registration/subscription state, calendar cache,
notifications and audits. SQLAlchemy async sessions use asyncpg; Alembic tracks
application migrations. Queue claiming uses PostgreSQL locking, leases and
heartbeat fencing. Auth.js uses its own adapter tables on the configured
PostgreSQL database; these are distinct from backend registered-user records.
Local Compose supplies a database; historical staging records identify Neon
as the database host and Railway as the API/worker host.

## Authentication and authorization flow

1. Auth.js redirects to Microsoft Entra using PKCE/state and exchanges the
   authorization code with Web application credentials.
2. JWT session data exposes the API access token to authenticated frontend
   requests; refresh-token logic renews expired API tokens.
3. FastAPI validates signature, expiry, issuer, tenant, audience and delegated
   scope, then binds the stable Entra object identity to application users.
4. Registration, subscription consent and meeting-level participant permissions
   govern access. Administrator and organiser checks govern privileged actions;
   approved attendee edit access does not itself grant approval authority.

Background Graph access uses application credentials, separately from the user's
delegated API token. A Microsoft Graph audience token is not the intended API token.

## Recording and AI processing flow

Opted-in calendar/OneDrive discovery or an authorized import/request creates a
durable recording job. The separate worker claims it, downloads the recording,
transcribes through the configured transcriber, runs the configured extractor,
and persists meeting/review data using queue ownership checks.
AssemblyAI is the default transcriber. The current extraction boundary calls
`app/ai/runtime_bridge.py` at both normal and completed-recording reprocess sites.
The default local `transcript_only` provider generates no summary/actions; the
local mock returns deterministic test summary/actions. Legacy Azure OpenAI and
Gemini extractor implementations remain in source, but the bridge rejects
external selections before instantiation and makes no external AI calls.
Recording processing and Gemini are disabled by default.

### Transcript persistence and retry

The pipeline saves speaker-labelled text, timed transcript segments and an
original raw-transcript snapshot before extraction. Extraction-only retries can
reuse saved transcription rather than downloading/transcribing again. Completed
recordings have a separate explicit reprocess path, preserving earlier review
results until replacement succeeds. Successful normal processing reaches
`awaiting_review`; failure/cancellation handling belongs to the existing durable
worker. Transcript and speaker-mapping edits are separate review API operations.

The `app/ai` foundation defines versioned requests/results, provider
interfaces, output validation, safe attempt metadata and route policy. Its
transcript-only provider performs no I/O. The bridge converts existing transcript
segments into the foundation request, runs one bounded attempt, enforces summary
and action-item scope, and returns the existing validated extraction result shape.
Decisions and additional generated sections are rejected. Failed output raises
before result writes; existing worker retries, cancellation fences and atomic
reprocess replacement remain responsible for safety. Attempt metadata is
ephemeral, with no new database writes.

### Provider architecture preparation

`app/ai/providers.py` centralizes the provider interface, both local providers and
immutable `ProviderDescriptor` metadata. `app/ai/registry.py` validates descriptors
and applies the server-owned policy before constructing one explicitly requested
local provider. Existing `transcript_only` and `mock` settings map to explicit local
policies; no new environment settings are introduced. `local_mock` is a test route
kind, not a cloud or verified private workspace.

External descriptors can carry configured model/prompt IDs and a credential
binding name, but have no executable factory, transport or credential resolver.
They remain non-executable even if enabled/approved in supplied policy. Gemini and
BusinessAI preparation uses these generic descriptors; names do not select code,
prove privacy, or establish an API contract. No external descriptors are registered
by default. Credential references are excluded from descriptor serialization and
representation. No secrets or transcripts are logged by this layer, and neither
selection denial nor provider failure causes automatic fallback. Actual private
workspace guarantees and all external transports remain future work.

## Review, action items and email workflow

Reviewers inspect transcript/speakers and edit permitted action-item fields.
The local Action Item Review component shows missing-field/low-confidence flags
and evidence. Local Phase 1A lists only approved actions from approved/sent
meetings the viewer can access; My Actions matches the exact normalized owner
email. This page is read-only and does not introduce assignment/task completion.

`build_meeting_email` renders both preview and final mail. In the local consistency
fix, reviewed database rows supply action task, owner and deadline; extraction
snapshots supply supplemental fields without review columns. Approval validates
selected attendees, checks the preview fingerprint and claims delivery under
database locking. With delivery enabled, Graph `sendMail` sends the approved
payload; delivery state/audits distinguish success, failure and ambiguous sends.
Disabled/local-test delivery can approve without sending. Approval marks actions
approved and records actor, time and recipients. A separate authorized
send-copy-to-self flow also exists. Processing notices and registration welcome
mail are separate workflows; `AUTO_SEND_EMAIL` is not the approval gate.
Approval authority belongs to the organiser or an administrator; approved
attendee edit permission alone does not grant it. Approval without delivery uses
`approved`, while successful final delivery uses `sent`.

## Sources

Frontend routes/components/auth/API/types, `app/main.py`, `app/models.py`,
`app/db.py`, `app/api/deps.py`, `app/auth/entra.py`, `app/api/reviews.py`,
`app/api/action_items.py`, `app/email_templates.py`, services, Graph, queue and
pipeline modules, Alembic migrations, and
[AI processing foundation](ai-processing-foundation.md).
