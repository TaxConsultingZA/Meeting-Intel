# Unified meeting and recording update

Scope: current authenticated subscribed user, within the existing OneDrive
Recordings and Documents/Recordings locations. No tenant-wide user/file scan,
permission expansion, transcription, email, review or task mutation.

The dashboard replaces Calendar-only sync with 更新会议和录音. It sequentially
calls calendar, discovery and matching steps, then refreshes saved lists. Each
step persists status, safe diagnostics, counts and last-success time. Partial
failure does not disguise old saved data as a fresh success. User-row locking
prevents concurrent submissions across replicas; successful steps have a
60-second server cooldown.

Discovery resolves supported roots once daily and follows folder delta pages.
Opaque cursors stay server-side, bound to the verified current user's drive.
At most 12 delta pages are read per step; remaining pages resume on the next
update. A 410 resets the cursor once. File writes and cursor commit together.
The first synchronization enumerates current files; later calls read changes.
Calendar reads are capped at six pages per window. Historical backfill reads
at most four weekly windows per pass and caches coverage for 24 hours. Exact
legacy metadata reads are capped at 12 per matching step.

Matching requires exact normalized title, unique occurrence, stable event ID
and iCalUId, recording time within the event (+10 minutes), and recording owner
participation. Cancelled calendar events, similar titles and nearby same-name
occurrences are not guessed. Prior explicit owner choices are retained. Only
processed_items display identity changes, not meetings or participant access.

The modal removes Discover files and all per-record manual association controls.
The true filename is primary and is available in full on hover/focus. Recording
date and size have separate columns; close remains outside the scroll container.
All shared date displays use Africa/Johannesburg. Legacy space-separated ISO
timestamps are normalized; Graph timestamps are persisted independently of any
calendar meeting. Missing dates are explicitly unavailable, never inferred from
discovery time. List reads use saved metadata rather than repeated Graph GETs.

Additive migration: 81c5f02a9d31, user_sync_states.details_json. Maintenance script
update_recording_inventory.py supports private backup, migrate, bounded run and
guarded rollback. Protected-table fingerprints are compared before/after.
Newly discovered recording ledger rows are preserved by rollback.

Validation: backend recording/discovery/matching/timezone/pipeline tests; frontend
unified workflow, partial failure, last-success, stale response, modal layout,
date parsing, task controls and API tests; TypeScript, ESLint and production build.
