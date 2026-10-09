# Project status

Snapshot: 2026-10-09. Based on the current working tree and local Git history;
Local development reference only.
HEAD is `139ed37` (2026-10-06). Existing uncommitted work is included explicitly.
Implementation does not establish deployment or successful live acceptance.
No application tests or external services were run for this documentation task.

## Purpose

Meeting Intel lets registered company users opt in to Outlook calendar and
OneDrive recording discovery, transcribe recordings, review meeting information
and action items, and explicitly approve selected email recipients.

## Current development phase

MVP stabilization and incremental review/workflow development. This description
summarizes repository evidence; it is not a declared release milestone.
The default extractor is transcript-only. Real recording consumption, Gemini,
and outbound email are disabled by default in `app/config.py`.

## Completed implementation in committed code

- Microsoft Entra login, API bearer-token validation, registered-user access,
  subscription consent, participant permissions, and administrator controls.
- Calendar cache, recording discovery/import and cross-user processing requests.
- Durable PostgreSQL recording queue with leases, heartbeat fencing, retry,
  cancellation and reprocessing controls; recording and review states are distinct.
- AssemblyAI transcription and transcript/speaker review; configurable structured
  extraction adapters exist, but their presence does not prove approved live use.
- Email preview, recipient selection, approval fingerprint, delivery state and
  audit records; administrator audit-log browsing and status diagnostics.
- Browser-timezone rendering, clearer access/outage feedback and loading/polling
  improvements, supported by committed code and associated test files.

## Completed local implementation (uncommitted)

- Recording lifecycle presentation and dashboard/import/admin UX refinements.
- Action Item Review: review flags, confidence, source evidence/context and
  validated edits with retained drafts on failure.
- Email consistency fix: reviewed action-item rows supply emailed task, owner
  and deadline; edits use the approval lock and reject claimed delivery states.
- Action Items Phase 1A (the requested documentation label): a read-only page/API
  for approved actions, access-scoped views, filters and pagination. No repository
  release or deployment under that phase name was verified.
- AI foundation runtime bridge connects the existing extraction boundary,
  including reprocessing, to local transcript-only/mock providers. Validated
  results use the existing review contract. Provider registry and policy
  preparation are present; external providers remain non-executable.

## In progress / incomplete

The local features above have implementation and associated test files, but
combined release validation and live acceptance remain pending. Uncommitted
does not by itself mean implementation is unfinished. Real external AI provider
integration is pending. Performance validation is partially pending according
to the existing stability audit; current progress beyond that record is unknown.

## Planned next steps documented in existing repository records

- Complete controlled real PostgreSQL concurrency, worker recovery and live
  transcription/extraction/email acceptance described in the offline runbook.
- Resume performance measurements when Neon resources permit; measure query
  counts, payload sizes and latency before broader optimization.
- Perform the administrator permission audit in the stability audit document.
- Select and authorize an external AI provider, transport, model and data policy
  before implementing real provider integration in the connected foundation.

## Unknown

Current cloud health, deployed commit/schema, provider approval, live credentials,
and acceptance of the uncommitted features were not checked. The September
deployment record is historical evidence, not confirmation of today's state.

## Sources

`README.md`, `app/config.py`, API/services/queue/pipeline source, frontend routes
and components, associated test files, local Git history and working-tree diff;
[historical status](meeting-project-status.md),
[stability audit](meeting-stability-audit.md),
[offline validation runbook](t6-t7-offline-validation.md), and
[AI foundation](ai-processing-foundation.md).
