# BusinessAI: synthetic test only, default closed

Updated 2026-10-29 (Asia/Shanghai). The earlier audit is recorded in
businessai-test-review-20261029.md; the authorized disabled release is described
in businessai-test-release-20261029.md. These are separate execution records.

## Current execution boundary

The meeting runtime accepts only local transcript_only/mock execution.
get_local_provider("businessai") always rejects, even with BUSINESSAI_ENABLED=true.
No worker, web endpoint, scheduler, Graph call, recording, mail or UI integration
invokes the synthetic test command. Deployment is not permission to analyse meetings.

The low-level adapter additionally requires enabled AND synthetic_test_enabled,
an exact HTTPS api.businessai.co.za/v1/chat/completions URL (port 443/default),
a configured model and a server-side secret. It accepts only the exact fixed text
`[Speaker A] Please send the report.`; other input fails before admission/HTTP.
Keys and the dedicated permit database URL are excluded from config serialization.

## Single-use admission across Railway replicas/restarts

The original SQLite monthly ledger alone is insufficient: each independent or
recreated disk can admit its own budget. It is retained as local usage evidence,
not a shared financial ceiling. Zero request/token limits still deny all sends.

A new PostgreSQL admission statement inserts the constant primary key
`meeting-intel-businessai-synthetic-v1`. ON CONFLICT DO NOTHING RETURNING permits
only one contender over the database's lifetime, across model/input changes and
replicas. It commits before HTTP; failures, cancellation, invalid JSON, unknown
usage and timeouts never refund it. Missing credentials/table, DB failure,
exhausted permit and TLS certificate/hostname validation failure all deny. Before
insertion, the adapter also verifies the public table primary key and rejects
RLS, table/schema ownership, superuser/role-management capabilities, or extra
UPDATE/DELETE/TRUNCATE/TRIGGER/public-schema-CREATE permissions. There is no migration or automatic DDL.

Before any future controlled test, the database administrator must provision a
DEDICATED shared PostgreSQL database/table, with the same DSN for every contender:

```sql
CREATE TABLE businessai_synthetic_permits (
    permit_id text PRIMARY KEY CHECK (permit_id = 'meeting-intel-businessai-synthetic-v1')
);
```

The runtime role needs INSERT and SELECT only on this table, no DELETE/UPDATE/TRUNCATE
or schema ownership. The operator must not switch databases, drop/recreate/reset
the table, restore an older snapshot, delete the local ledger or change PERMIT_ID
to retry. All such administrative changes can defeat any durable limit. Shared
PostgreSQL behavior is covered by mock statement/denial tests, not live acceptance;
no database was provisioned or changed in this run. Do not claim an enabled shared
test deployment is accepted until concurrency/restart checks pass on its dedicated DB.

## Operator channel (not executed this run)

Only after authentication, model entitlement and actual quota are verified:
`python -m scripts.businessai_synthetic_test`.
This command takes no transcript argument and uses no meeting database records.
It requires all of: BUSINESSAI_ENABLED=true; BUSINESSAI_SYNTHETIC_TEST exactly
`confirmed-account-model-quota`; BUSINESSAI_TEST_DATABASE_URL (server secret);
BUSINESSAI_CHAT_URL; BUSINESSAI_MODEL; BUSINESSAI_API_KEY;
an absolute writable BUSINESSAI_LEDGER_PATH; BUSINESSAI_MAX_REQUESTS=1; and an
explicit BUSINESSAI_TOKEN_BUDGET up to 4096. Defaults remain false/empty/zero.
Never put the marker/credentials in frontend variables, startup or health checks.

Command hard caps: one shared lifetime admission, input 2048 UTF-8 bytes,
output 256 tokens, POST deadline 30 seconds, shared admission deadline 5 seconds,
no redirects, retries, streaming or automatic fallback. The input itself is fixed
and much shorter than the cap. Byte reservations include system prompt, 512
estimated overhead and output cap; they are NOT a verified tokenizer or monetary
limit. Actual usage is checked and retained before JSON/source-quote validation.
Uncertain calls consume admission. No catalog estimate is treated as actual price.

Results still require valid summary/action JSON and exact source quotes. Offline
save-boundary tests inject the synthetic provider explicitly; they do not enable
the meeting bridge or establish production persistence acceptance.

## Historical preparation evidence (not reverified this run)

## Official evidence checked 2026-10-29

Sources: [Integrations](https://docs.businessai.co.za/developer/access),
[official examples](https://docs.businessai.co.za/app.js?v=20261001e),
[public config](https://api.businessai.co.za/auth/config).

- Quickstart confirms POST /v1/chat/completions, Bearer, model/messages.
  Playground sends max_tokens and stream, with UI range 1–8192. This is interface
  evidence, not verified enforcement for each model. Schema controls are shown;
  actual strict schema behaviour for each runtime remains unconfirmed and the
  adapter does not request it.
- Non-streaming example: choices[0].message.content, finish_reason=stop, usage
  prompt_tokens/completion_tokens/total_tokens. Chat-shaped output does not by
  itself establish valid Meeting Intel JSON or grounded actions.
- Public chat catalog: businessai-chat, mistral-7b-instruct-v0.2,
  glm-4.7-flash:latest, gemma4:e4b, qwen2.5-coder:32b. Actual account grants and
  runtime availability are unconfirmed. businessai-chat explicitly routes vLLM
  first and can fall back to Ollama server-side. Pinning the application model
  does not pin a backend or establish its privacy policy.
- Public concurrency: chat_max_inflight=24, per-subject=4. These are NOT RPM/TPM.
  Key-creation UI defaults are RPM 60, TPM 120000, monthly tokens 10000000.
  Actual key limits, remaining quota and reset windows: UNCONFIRMED.
- Chat 503 example is a plain detail field describing no eligible healthy
  runtime. Exact 400/401/403/408/429/504 error bodies, Retry-After guarantees and
  failed-request billing: UNCONFIRMED. Local mappings are 401/403 configuration,
  429 rate_limited, 408/504/timeouts timeout, other 5xx/transport unavailable,
  other non-200 configuration, malformed usage/output invalid_output. Raw vendor
  errors never enter public failure messages.
- estimated_cost_per_1k_tokens appears in the catalog (router: 0.0008).
  Currency, input/output billing split, taxes, signed actual price, account
  credit and enforceable hard spend ceiling: UNCONFIRMED. Do not turn catalog
  estimates into actual charges or infer price from historic token usage.

## Chat data boundaries: all unconfirmed

The reviewed Integrations examples/public config do not establish these for chat:

- Request/response retention duration: UNCONFIRMED.
- Gateway/provider/debug/trace log content and retention: UNCONFIRMED.
- Deletion mechanism, backup deletion and deletion SLA: UNCONFIRMED.
- Training/fine-tuning/evaluation reuse and opt-out defaults: UNCONFIRMED.
- Processing/storage regions, subprocessors and cross-border transfers:
  UNCONFIRMED. Runtime names mentioning DGX are not contractual regions.

Do not substitute document-extraction zero-persistence claims or Knowledge
retention settings for chat policy. Ask the BusinessAI platform/data-protection
owner for a chat-specific agreement covering all backends/logs/backups, deletion,
training and regions/subprocessors. Ask the account billing administrator for
model grants, RPM/TPM, remaining monthly quota/reset, price/currency, failure
billing and evidence of a hard limit. These are boundary questions, not renewed
permission to use the API.

## Controlled validation gate

Mocks must cover synthetic transcript segments through admission, chat, usage,
JSON/evidence and participant validation to the save boundary. Ordinary tests
must deny real sockets. Mock audit commits are not live database acceptance.
At most one short synthetic request may be sent only after authentication, model
access, documented token limiting and actual quota/budget are verifiable. Use a
persistent ledger, max_requests=1 and explicit token cap. Record numeric usage
and account-visible before/after consumption. Stop without retries on errors or
missing usage. Do not create keys, send real meetings/recordings/PII, deploy,
migrate, start jobs, call Graph or send mail for this validation.

Keep production BusinessAI disabled until chat boundaries and the complete
transcript-to-reviewed-result path are accepted. English-only UI review is a
separate follow-up; no UI copy changes belong in this preparation branch.
