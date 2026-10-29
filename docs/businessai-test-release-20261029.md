# BusinessAI disabled test release — 2026-10-29

This follows the earlier local review; release is now explicitly authorized.
It does not authorize production meeting analysis, queued recording processing,
Graph, mail, data migrations or changes to recording controls.

## Reviewed source and deployment scope

Remote main at review: bcbbb6b7d1d73d570e34bc7065c71ef2cdb6b657.
Preparation commit: 9874765388a3f1ac1c47c5c9dd901e29204cc7cf (direct child).
Only the independent BusinessAI worktree is used. Local main and other worktrees,
including the recording/loading review, are not merged or reset. The release is
pushed on its BusinessAI branch and deployed from an archive of the reviewed
commit; no worktree-local untracked files are uploaded.

Target: Railway project meeting-intel-staging
(059e3add-9746-4baa-90e1-58d4fa5f2559), existing environment named production
(4e9319c2-9b91-4db7-875c-5af582b27d4e), API service only
(e1ac0606-9576-4bf7-b0b2-c414d90c46de).
The environment name does not make this a real-meeting AI rollout. No frontend
release is needed for this backend-only change. The worker remains stopped.

Required deployed settings: EXTRACTOR_IMPL=transcript_only,
BUSINESSAI_ENABLED=false, BUSINESSAI_SYNTHETIC_TEST=disabled,
BUSINESSAI_MAX_REQUESTS=0, BUSINESSAI_TOKEN_BUDGET=0.
Set them with --skip-deploys, then deploy API source once. Preserve all other
variables, especially RECORDING_PROCESSING_ENABLED. Existing SERVICE_ROLE=api,
ENABLE_SCHEDULED_SYNC=false and ENABLE_AUTO_RECONCILE=false were checked first.
The start command runs only uvicorn; no pre-deploy command or cron is configured.

## Default-closed behavior

Meeting/recording processing uses local transcript_only; the runtime factory
always rejects BusinessAI selection, independently of the enable variable.
There is no BusinessAI web route/button, startup invocation, scheduler or worker
hook. AssemblyAI transcription remains a separate chain and is not started here.

The only operator command is python -m scripts.businessai_synthetic_test. It has
no text argument or meeting lookup; the only input is the built-in short synthetic
fixture. It needs both the enable flag and exact test marker, explicit key/model/
URL/ledger/quota plus dedicated shared PostgreSQL configuration. The command caps
requests at 1, input at 2048 bytes, output at 256 tokens, HTTP at 30 seconds and
reserved tokens at 4096. No retries, redirects, streaming or backup models.
Only safe status/failure codes and numeric usage are printed; no generated body,
key, DSN or raw settings/database/transport exception is printed.

Shared admission checks certificate/hostname-verified TLS, a primary key on
public.businessai_synthetic_permits.permit_id, and a non-owner INSERT/SELECT role
without destructive privileges, elevated capabilities or public schema CREATE.
It rejects RLS. A single constant permit key is inserted atomically in autocommit
before the HTTP attempt. A crash or failure never refunds it. SQLite is secondary
local accounting only and is not a distributed request ceiling.

## Test execution decision and account evidence

Real BusinessAI chat attempts in this release run: **0**.

The deployment API variables contain no BUSINESSAI_TEST_DATABASE_URL or
BUSINESSAI_API_KEY and no configured URL/model/local ledger path. Consequently
the dedicated store/table/role and cross-process/concurrent admission have not
been verified on the deployment database. No permit database was created or
substituted with the real meeting database, and no live admission was consumed.
Only mocked shared-store tests have passed; they do not establish live DB behavior.
The test channel is unavailable by design until these prerequisites are met.

User-provided screenshot evidence (not a fresh authentication check): existing
key label Meeting Intel local test, model label businessai-chat, 60 RPM,
120,000 TPM. Historical Analytics displayed 1 request and 247 tokens. These are
NOT new requests in this run and do not demonstrate remaining balance, reset
window, current authentication, actual currency/prices or a hard monetary budget.
The value 10,000,000 is not treated as remaining quota; a graph's Mistral label
is not treated as the key's complete model entitlement.

Current browser inventory shows BusinessAI Workspace at
https://docs.businessai.co.za/admin/account. No page body or additional account
credentials were read, and no repeat of the previously failed tab binding was
attempted. The prior tab-session conflict remains an account-inspection limitation.
Analytics before/after delta, returned usage and visible cost this run: **unknown**.
No actual-price or monetary-ceiling claim is made.

## Verification before release

139 tests passed across the BusinessAI provider/command, shared permit,
staging settings, runtime bridge and provider registry modules. Coverage includes
success, zero/exhausted budgets, oversized/rejected inputs, transport/HTTP timeout,
missing/malformed/over-limit usage, duplicate invocation, no fallback/redirect,
local ledger atomicity, unsafe/missing shared-store denial and sanitized output.
Python compilation and git diff --check passed. No unrelated full suite or UI
build was run. The Railway Docker build supplies the deployment build check.

Post-deploy verification must record the deployment ID/status, exact runtime
revision, disabled settings, health/OpenAPI/auth boundary checks, unchanged worker
deployment and unchanged recording control. This document is the reviewed source
record; deployment results are recorded in the final release response.

## Real meeting processing remains closed

Accessible evidence has not established chat request/response/log/backup retention
and deletion, training/evaluation uses, processing/storage regions/subprocessors,
or actual billing rules. Applicable chat documents are still needed from the
BusinessAI platform/data-protection owner or SP. Document extraction claims must
not be applied to chat. Code deployment is not real-meeting AI acceptance.
