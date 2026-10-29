# BusinessAI test readiness review — 2026-10-29

Review window: approximately 18:35–18:43 Asia/Shanghai (UTC+08:00).

## Decision

YES: deployable in principle as inert, default-disabled test preparation code,
with EXTRACTOR_IMPL=transcript_only, BUSINESSAI_ENABLED=false, no synthetic marker,
no test DSN and request/token limits zero. No push or deployment was performed.
This conclusion does not accept an enabled test deployment: the shared database
has not been provisioned/live-tested, and authentication/model/quota are unverified.

NO: real meetings must not be processed. Chat privacy/retention/training/region,
subprocessors, actual pricing and account limits remain unconfirmed. The meeting
runtime now rejects BusinessAI even when its environment enable flag is true.

## Git scope and baseline

The supplied worktree was clean at HEAD 9874765388a3f1ac1c47c5c9dd901e29204cc7cf.
Local main is d965b6516cc4efa7a9ca6be5efe4b3feddb076fc; HEAD is 12 commits ahead,
zero behind. HEAD's direct parent is bcbbb6b7d1d73d570e34bc7065c71ef2cdb6b657.
Read-only git ls-remote confirmed that parent is the remote main tip this run.
The supplied commit itself has exactly 10 changed files. Do not compare the whole
branch against stale local main and accidentally re-release unrelated history.
The main checkout's existing dirty files were read through status only and retained.
No branch reset, cherry-pick, merge, push, deploy, job execution or DB migration.

## Website/account evidence and access failure

Observed browser inventory title: BusinessAI Workspace.
Observed URL: https://docs.businessai.co.za/developer/quickstart .
Attempted at approximately 18:35–18:37 Asia/Shanghai. Binding existing tab failed:
`Tab 1050188820 is already part of browser session 01a186a7-52f0-7ac3-8af4-b22900b8e9be`.
No repeat of that failed binding; no key reveal, screenshot capture, authentication
interaction or account mutation was attempted. Page body was NOT inspected.

Public web fallback at approximately 18:40 also returned Internal Error / not
accessible for the quickstart URL, https://docs.businessai.co.za/developer/access
and https://api.businessai.co.za/auth/config . It did not bypass the account session.

- Website explicitly established THIS RUN: none of the requested chat rules.
- Account-page evidence THIS RUN: none. Your keys, Analytics, Administration,
  Billing and Usage could not be reached through the blocked binding. Their
  exact current titles/URLs are unknown; no inferred URLs are presented as visits.
- Historical preparation notes remain labeled historical in the adapter document;
  they are not current account verification. Extraction endpoint policies are
  not evidence of chat retention.
- Still unconfirmed: request/response and gateway/provider/debug log storage,
  retention periods, deletion paths/SLA/backups; training/evaluation reuse;
  processing/storage regions, subprocessors and transfers; key model grants,
  remaining balance, quota/reset window, RPM/TPM; actual input/output unit prices,
  currency, tax, failure billing, current used quantity and enforceable hard budget.

## Review of all ten supplied files

- app/ai/businessai.py: pinned model; single non-streaming POST; no redirect,
  retry or client fallback; strict usage arithmetic/output limits and grounded
  JSON validation. Previously arbitrary HTTPS destination and real transcript
  routing were possible after opt-in. Now restrict exact vendor endpoint,
  fixed synthetic text and separate closed-by-default synthetic gate; require
  shared admission before POST; cap adapter input/output/time at 2048/256/30.
- app/ai/businessai_budget.py: reviewed, unchanged. BEGIN IMMEDIATE protects only
  contenders sharing one SQLite file. Reservations survive unknown outcomes;
  reported invalid usage locks sends. Monthly UTC reset is not a verified vendor
  quota window. Multiple independent/ephemeral disks defeat aggregate budget.
- app/ai/providers.py and app/ai/registry.py: reviewed, unchanged. Descriptors
  cannot execute alone; exact config/model binding and no fallback. enabled is
  also used as approval, so this must not be read as real-meeting privacy consent.
- app/ai/runtime_bridge.py: removed the cloud factory/config construction.
  Meeting runtime accepts local routes only; test injection is explicit in mocks.
- app/config.py: reviewed defaults false/empty/zero; exclude API key from
  model serialization as well as repr. Real-meeting BusinessAI selection fails.
- app/tests/conftest.py: reviewed, unchanged; synthetic secrets/default zero
  budgets and session-wide real-socket denial. No real credentials consumed.
- app/tests/test_ai_staging_settings.py: reviewed, unchanged; route selection
  alone does not enable cloud. Explicit runtime rejection has separate coverage.
- app/tests/test_businessai_provider.py: reviewed and adjusted to explicit mock
  synthetic injection; retained usage/error/timeout/cancellation/local atomicity
  tests and added shared-permit denial before HTTP.
- docs/businessai-offline-adapter.md: replaced execution/control description;
  original public-site claims clearly marked historical, no current-account claim.

New files: app/ai/businessai_test_permit.py, app/tests/test_businessai_test_permit.py,
scripts/businessai_synthetic_test.py, and this report. No UI/recording changes.

## Shared test limit and remaining operational acceptance

The only operator command uses a fixed synthetic fixture and fixed meeting UUID,
never reads meeting records, and never runs from the worker/startup/health checks.
It clamps local caps to 1 request, 4096 reserved tokens, 2048 input bytes, 256 output
tokens and 30-second HTTP deadline. Shared admission adds at most 5 seconds.

PostgreSQL unique insertion of a constant permit key allows at most one lifetime
admission across every replica using the same dedicated database. It commits
before the external attempt. No refund/retry/reset exists. Missing config/table,
DB failure, timeout and consumed permit deny. A crash after admission may spend
the permit without sending: conservative by design. SQLite remains usage evidence.

Operator provisioning SQL and least-privilege requirements are in the adapter
document. This run did not contact/provision PostgreSQL. Mocks verify SQL, denial
and cleanup, not a real cross-replica deployment. All contenders must use the SAME
durable database, never a per-replica DB or old restored snapshot. A changed DSN or
administrator table reset defeats this scope and must not be used to retry.
The single admission limits request count; it is NOT a verified monetary ceiling
or proof that the vendor enforces max_tokens. Account-side limits remain needed
before an enabled test is accepted.

## Controlled validation record

Real BusinessAI chat requests: **0**. Account auth/model/quota gates did not pass.
Usage: **not available**, not assumed zero tokens from an API response.
Analytics before/after: **unavailable**. Visible price/cost: **unavailable**.
No incremental API request was initiated; no claim is made about account-wide
existing charges. No recording, real transcript, names, email or customer input
was transmitted; no Graph or mail call, retry or production AI enablement occurred.

Related verification: provider, shared permit, staging settings, runtime bridge,
provider registry test modules; Python compilation of changed execution modules;
git diff --check. Final result: 133 passed in 3.14 seconds; compilation and diff checks passed. No frontend build or
unrelated full-suite repetition was needed. No live DB concurrency claim.

## At most three follow-up questions

1. BusinessAI platform/data-protection owner: for chat and every routed backend,
   what are request/response/log/backup retention and deletion SLA, training reuse
   defaults, processing/storage countries and current subprocessors?
2. BusinessAI account/billing administrator: for this key, provide actual model
   grants, remaining quota/reset and RPM/TPM, price/currency/failed-call charging,
   and evidence of an enforceable hard token/spend budget.
3. Meeting Intel test infrastructure owner: which dedicated durable shared
   PostgreSQL database and INSERT/SELECT-only role will hold the one-use permit,
   and can concurrent contenders plus process restart be verified without an
   HTTP call before any explicitly authorized synthetic test?
