# AI Processing Foundation — Phase 1

The local-only runtime bridge now connects the foundation to both existing
extraction calls in `app/pipeline/steps.py`: normal processing and safe completed
recording reprocessing. No dependencies, settings, database columns, migrations,
workers or queues are introduced. Review, approval, email and authorization
continue to use their existing workflows.

## Boundaries and data flow

Existing transcription -> ProcessingRequest v1.0 -> local AIProvider -> foundation
process/validation -> existing RichExtractionResult persistence -> awaiting_review.

Normal processing still commits the transcript before extraction. Reprocessing
still builds a replacement off-row and installs it only through the existing
lease-fenced atomic result commit. Failed/invalid AI output cannot replace saved
results. The previous successful transcript remains available after failed
reprocessing; the newly attempted reprocess transcript is not separately persisted.

The local TranscriptOnlyProvider returns no generated insights and performs no
I/O. `runtime_bridge.get_local_provider` translates the existing `transcript_only`
and `mock` implementation names into explicit server-owned registry/policy
selection. Both local providers now live in `app/ai/providers.py`; the bridge keeps
its previous local test seam. The deterministic mock echoes transcript text
as a test summary/action, without claiming semantic extraction or guessing owners
or deadlines. External and unknown selections fail with a safe configuration
error before provider construction; the legacy external factory is never called
by the bridge. No fallback or external adapter is added. Transcription remains
the existing separate Transcriber interface.

## Contract

Requests contain a meeting UUID, language hint, and immutable transcript segments
with unique IDs, speaker labels, text, and optional real timestamps. Unknown
timestamps stay null. Only version 1.0 is accepted; extra envelope fields fail
validation. No credentials, recipient lists, access grants, or approval state are
part of the request.

Outputs wrap the existing RichExtractionResult to retain its review/email
compatibility and optionally carry decisions with agreed/proposed/unresolved
status and source-segment/quote evidence at the library level. The runtime bridge
rejects decisions and all non-default rich sections outside summary/actions;
only summary and action items can reach the current extraction boundary.
Existing action grounding and known-participant validation is
reused. Evidence containment does not prove semantic correctness: summary
grounding, ownership validation improvements, legacy alias/deadline validation,
long-transcript limits and human evaluation remain subsequent work. Decisions
remain unsupported by the runtime bridge, review API and email templates.

## Metadata and persistence

Each attempt records a unique run ID, canonical request hash, meeting ID,
provider/model/prompt identity, contract version, attempt number, UTC timestamps,
elapsed duration, completion status and safe failure classification. Identical
inputs produce identical fingerprints, but this is not provider idempotency or
deduplication. No transcript text or exception messages enter metadata.

metadata_payload(existing, metadata) prepares a deep-copied JSON object with an
additive ai_processing key. It preserves other fields and stores only the latest
attempt to bound growth. It does not persist anything. The runtime bridge also
does not persist attempt metadata or introduce additional commits. Its runner
attempt counter describes this single invocation, not the durable job attempt
count. A future integration may
use Meeting.extracted_json without a schema migration, but must reread current
data and use the existing lease/cancellation-fenced commit. A process crash cannot
produce durable attempt metadata until such integration is approved. Full run
history and token/cost telemetry require a separate design.

## Failure and retry ownership

process executes exactly one attempt with a configurable timeout. Adapters report
ProviderFailure codes; transient timeout/rate-limit/unavailable codes are
retryable. Invalid output, configuration and unknown failures are nonretryable.
No provider exception details are returned. Cancellation is re-raised as a
CancelledError subtype carrying metadata; it is never converted to a retry.

RetryPolicy computes bounded exponential delay and enforces an attempt budget.
It never sleeps, schedules, calls a provider, or changes a job. Its classification
is advisory for future integration: today's recording worker retry/backoff
behavior is untouched. The bridge raises a safe failure-category exception for
failed/invalid output and lets the existing worker apply its current attempt
budget/backoff, including its existing treatment of invalid results. It does not
use RetryPolicy or schedule retries. Cancellation propagates and the existing
post-extraction commit fence remains intact. Timeouts depend on a cooperative
async adapter; providers must not block the event loop or suppress cancellation.

## Next integration gates

1. Select and authorize a provider and its data-handling terms.
2. Add contract tests for its adapter and an approved evaluation dataset.
3. Define prompt versions, transcript/token limits and retry/idempotency semantics.
4. Add durable per-attempt metadata through existing fenced persistence.
5. Validate approved external output through this boundary while preserving human
   approval and mail; local summary/actions already use existing review shapes.

External calls, automatic approval, recipient selection, permission changes,
recording lifecycle changes and mail changes are outside Phase 1.

## Runtime bridge verification

Offline tests exercise local success and transcript-only output, fail-closed
external selection, safe provider failures, invalid/out-of-scope output,
known-participant validation, unknown timestamps, cancellation, transcript reuse,
previous-result preservation and the actual review serializer. Tests use mocked
database/Graph/transcription operations under the shared network-denial fixture.
They do not establish live PostgreSQL locking or external-provider readiness.

## Provider architecture preparation — Phase 2

`ProviderDescriptor` is an immutable, provider-neutral preparation contract:
capabilities/route kind, optional configured model and prompt identifiers, optional
server credential binding name, and a local-only factory key. It contains no
transport endpoint or secret value. Credential references accept identifier names
only and are excluded from representation/serialization; no resolver reads them.
Only trusted backend code may supply descriptors and policy, never frontend data.

`ProviderRegistry` revalidates descriptors and policy, rejects duplicate identities,
selects an explicit requested route, and checks factory/provider identity before
returning an instance. Executable factories are restricted to the two reviewed
local providers. Cloud/workspace descriptors cannot bind a local factory and
cannot execute even when their capability flags and selection policy permit them.
Factory or processing failures never choose another provider. No dynamic imports,
credential lookup, response/transcript logging or provider network transport exists
in this registry.

Gemini and BusinessAI can be represented by generic preparation descriptors with
server-chosen IDs, without vendor routing branches or model defaults. No external
descriptor is registered by default. A provider name does not establish cloud or
workspace capabilities; BusinessAI's actual API/authentication/deployment contract
remains unknown. Legacy Gemini/Azure extractors are unchanged and remain outside
the runtime bridge. Enabling an external descriptor does not enable these legacy
extractors. Real adapters need a separately approved implementation and data policy.

The compatibility configuration recognizes only `transcript_only` and `mock` and
creates explicit local policies. It uses no new environment variables or private
environment values. The transcript-only route uses disabled-AI mode without
analysis features; mock uses capability mode for summary/actions. Neither route
claims workspace privacy. To prepare future routes, trusted backend code can
construct a registry with additional inert descriptors; current runtime settings
still cannot execute them.

## Processing policy and runtime selection

`app.ai.policy` remains pure selection logic with no transport or provider
construction. The runtime bridge now uses it through the registry. Only existing
local providers are registered for runtime use. Existing authorization, recording
retries, audit events and extraction behavior remain unchanged.

ProcessingPolicy records a policy version, disabled/capability/privacy mode,
ordered provider allowlist, workspace allowlist, required MVP features and contract
version. ProviderCapabilities describes a deployment route's enabled/approved
status, contract versions, features and verified privacy settings. All definitions
are immutable; provider enablement and approval default to false. Gemini and
BusinessAI are future route configurations, not built-in privacy guarantees.

Capability mode selects the first enabled, approved, compatible analysis route in
the policy allowlist. Workspace routes also need an allowed workspace identity.
Privacy mode requires a verified workspace with cloud forwarding and automatic
fallback disabled. Disabled mode permits only an explicitly allowed/approved local
transcript-only route, and cannot fulfill a request for AI features. Analysis modes
never silently substitute transcript-only processing.

Explicit provider selection never falls back. An absent or disallowed route,
incompatible capabilities or duplicate registry identity returns a safe denial
without provider or workspace selection. Invalid policy/capability definitions
raise validation errors before selection; callers must not turn them into a default
route. Selection is not retry/failover scheduling and does not grant permissions.

Policy and capability values must come from trusted server configuration, not
client-supplied privacy claims. Verification of workspace isolation, actual model
destinations, retention and fallback configuration remains an organizational gate.
No-forwarding privacy is a conservative initial policy: other deployment options
need a separately reviewed policy extension. The privacy scope is AI analysis;
this layer does not change or certify the existing transcription data boundary.

The registry enforces explicit selection and identity at the current local runtime
boundary. The low-level runner can still be invoked independently by trusted Python
code; registry policy is not a sandbox against arbitrary backend code. External
integration must additionally pin the selected route for retries and persist
effective policy/route metadata through existing fenced writes and audit
conventions. No durable policy metadata is introduced in this phase.

Offline registry/policy tests cover disabled/unapproved routes, policy denial,
explicit selection, invalid bindings/identities, non-executable external
preparations, no fallback, credential-reference handling and local compatibility.
Bridge tests retain invalid-response rejection and verify no transcript/raw-error
logging. Existing worker, cancellation, preservation and review tests remain part
of the focused regression checks.
