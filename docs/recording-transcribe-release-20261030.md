# Per-recording transcription release — 2026-10-30

This release is based on API deployment source 69ce8939f00c9d0165299088d90a49b443a67429,
not only the older main/review base bcbbb6b. The already deployed BusinessAI
guarded adapter and default-off settings remain unchanged; extractor stays
transcript_only, BusinessAI enabled=false, request/token budgets=0, emails=false.
No navigation-loading-review changes are included.

## Database gate completed

- Verified Neon project shiny-recipe-30189164, branch br-crimson-hill-b2qrut21,
  endpoint ep-patient-queen-b2jhut4w, PostgreSQL 18.
- Custom logical dump from a consistent exported snapshot at
  2026-10-30 09:55:40.814862 UTC; 519736 bytes,
  SHA-256 260bdeed5696c459bbcfd1c8698991a3b5d24494efe9027d2f39f01182e4b332.
- Restored into an isolated loopback PostgreSQL 18 Docker server. All 19 public
  table row counts and data fingerprints matched; restore container removed.
  Backup is outside the repository in an ACL-protected private directory. This
  proves logical restore, not a Neon Console/PITR restore or source role/grant restore.
- Initial dump attempt exceeded 180 seconds. A second verbose attempt with a
  15-second lock-wait limit and 300-second overall timeout completed. No schema
  migration or deployment was attempted before successful restore validation.
- Controlled migration 51d8f2a7c903 -> 92d6a10f4e72 completed with processing false
  and the worker stopped. All 22 legacy job rows and meeting fingerprints were
  unchanged. Legacy authorization fields are NULL, submission_count=0.

## Processing contract

The existing per-recording Transcribe action creates one permission-checked job.
No global Transcribe action is added. Explicit durable admission is required for
claim/recovery. A committed reservation precedes the sole paid provider POST;
uncertain submission outcomes are not automatically replayed. Completed jobs are
never automatically claimed again. Failure needs explicit review, not blind retry.

An optional temporary fence, PROCESS_ONLY_DRIVE_ID plus
PROCESS_ONLY_DRIVE_ITEM_ID, allows waiting for one specified recording before its
job exists. Both fields must be provided together, otherwise claim/recovery fail
closed. They intersect PROCESS_ONLY_JOB_ID when that is also set. Empty recording
filters retain normal operation. The first live acceptance is restricted to
test03; the user, not the agent, will click once. No job is pre-created.

The test03 Graph identity/owner checks and full audio decode passed: 88 seconds,
657214 bytes, peak -11.2 dB, about 42.221 seconds above the -40 dB silence threshold.
Energy detection is not a claim of speech/language accuracy. No content/link is
included here. There were no existing jobs for this recording at preflight.

## Validation on integrated source

- Worker, recording API, transcription, default-off AI settings and BusinessAI
  one-use-permit tests: 112 passed.
- Integrated local mock pipeline on real isolated PostgreSQL: 1 passed.
- Temporary recording fence: 50 worker/settings tests, plus 2 isolated PostgreSQL
  claim/recovery/filter tests passed.
- Existing review evidence covers the original 15 PostgreSQL cases, strengthened
  5-case rerun, 5 synthetic browser scenarios, UI/static checks and production build.
  Unchanged UI files remain the reviewed versions; real deployment builds are
  checked independently. No production transcription is used for test assertions.

## Deployment and recovery

Deploy API/frontend and worker from an archive of this exact release commit, with
processing initially false. Worker deployment starts a process even when false;
verify source hashes and the applied migration before enabling. Keep the exact
recording fence for test03 until acceptance and queue review are complete.

Pause by setting processing=false for both services (without automatic redeploy),
then stop the active worker deployment; settings are cached and variable storage
alone does not stop an existing process. Keep schema and submission history.
Application rollback must not re-enable an old worker that ignores admission.
Never reset count/attempts or put an uncertain submission back in pending. Known
provider IDs can be queried read-only; safe completed-result import remains a
separate maintenance procedure. No automatic approval or mail is enabled.

Actual commit/deployment IDs, runtime flags, acceptance state and resource
observations are recorded in the local release execution evidence and final user
report; code deployment alone is not automatic-transcription acceptance.
