# Known issues and verification limits

Snapshot: 2026-10-09. Configuration pitfalls below follow current source; they
do not imply an incident was reproduced during this documentation task.
Local development reference only. “Historical fix” refers to existing repository
records, not fresh verification. No private environment values were inspected.

| Issue | Cause / evidence | Solution or workaround | Current status |
| --- | --- | --- | --- |
| Local frontend port mismatch | Repository references use 3000. The reported previous use of 3010 has no supporting incident record in the checked files. | Start explicitly on 3000; if choosing 3010, align startup, `AUTH_URL`, Entra callback, CORS and email `APP_URL` as described in the local runbook. | 3000 verified; previous incident cause/resolution unknown. |
| Local database port mismatch | Compose publishes 5434, but backend settings default to 5432. | Set `DATABASE_URL` to the dedicated local database's host port 5434. | Confirmed configuration mismatch; active failure unknown. |
| Auth callback/session problems | Auth source comments identify issuer mismatch, a Web confidential-client registration, changed provider subjects and old encrypted local sessions. Exact previous callback failure is not logged here. | Use the tenant v2 provider and exact `http://localhost:3000/api/auth/callback/microsoft-entra-id`; verify Web secret, tenant and API scope/audience. Keep `AUTH_SECRET` stable and sign in again after changes. | Mitigations present in source; current tenant configuration and successful local login unknown. |
| CORS | Historical status explicitly records a fixed staging CORS issue; exact cause/configuration is unknown. Locally, only `http://localhost:3000` is allowed by default; 3010 and `127.0.0.1` are distinct origins. | Set `CORS_ORIGINS` to a JSON list of exact intended origins and check `NEXT_PUBLIC_API_URL`. Diagnose connection/token failures separately. | Historical staging fix recorded; current local CORS not exercised. |
| Backend fails to start | Source requires tenant/client/secret settings and performs PostgreSQL initialization/seeding at startup. The previous startup exception/root cause is not recorded in the checked evidence. | Run from root with required settings and a reachable local PostgreSQL database/schema; inspect the actual exception. API command explicitly uses port 8000. | Startup dependencies confirmed; previous cause and current runtime status unknown. |
| Recording queue does not progress | API queues jobs; a separate worker consumes them and processing defaults off. | Check worker process, shared local database, job/lease state and processing gate before enabling external processing. | Confirmed design constraint; no active stall verified. |
| Railway versus local processes | Historical remote API/worker hosting is Railway. Local Uvicorn and Next.js run independently; pointing the browser at a remote API changes which service it calls. | Use the local API URL on port 8000 and dedicated local database for local development. | Hosting relationship documented historically; current remote availability unknown. |
| Neon database dependency | Historical staging uses Neon PostgreSQL; the stability audit defers validation until quota recovery. Railway hosting does not supply evidence of Neon availability. | Check database resources separately when working remotely; use local Compose for this runbook. | Historical quota-related validation gap; current quota/schema/health unknown. |
| Environment loading and aliases | Backend reads root `.env`; frontend startup has no explicit loader for that root file. Backend accepts frontend-style credential aliases. | Use frontend `.env.local` or injected values, avoid conflicting aliases and restart after changes. | Source-confirmed pitfall; no private values checked. |
| SSL/pooling mismatch | Frontend's SSL heuristic checks for `localhost`; queue advisory locks need direct/session pooling. | Use `localhost` for the supplied local setup; verify pooling/SSL before remote worker use. | Source/runbook constraints confirmed; actual connections unverified. |
| Stale README setup | README mentions a Local Mock login absent from current frontend; sample Service Bus fields have no settings implementation. | Follow [local development](LOCAL_DEVELOPMENT.md) and current source. | Confirmed stale guidance; original README left unchanged. |

## Unresolved risks and planned validation

- Existing uncommitted Action Item Review, email consistency, Action Items Phase
  1A and UX changes have source/test coverage files, but test execution, deployment
  and live acceptance were not verified here.
- Action owners are free text: name-only owners do not appear in My Actions.
  All Accessible remains limited to the viewer's meeting permissions.
- Real PostgreSQL concurrent workers, crash recovery and controlled external
  transcription/extraction/email tests remain explicit offline-runbook follow-up.
- A network timeout after Graph accepts an email can leave ambiguous delivery;
  current code preserves `sending` for ambiguous outcomes. Reconcile evidence
  before retrying rather than assuming delivery failed.
- Performance audit defers broad `reviews/all` pagination, large meeting-detail
  payload changes, calendar extracted-data reduction and further N+1 work until
  representative measurements. Administrator permission auditing remains planned.
- Provider approval, model selection, data policy and live integration for the new
  AI foundation remain unresolved; a privacy policy flag alone proves no provider
  privacy properties.
- No live cloud checks, database inspection or application tests were performed
  here. Historical deployment/test counts should not be read as current results.

## Sources

`app/config.py`, `app/main.py`, `app/api/reviews.py`, `app/queue/worker.py`,
`frontend/src/lib/auth.ts`, `frontend/src/lib/api.ts`, frontend environment example
and configuration, `docker-compose.yml`, `README.md`,
[historical status](meeting-project-status.md),
[stability audit](meeting-stability-audit.md), and
[offline validation runbook](t6-t7-offline-validation.md).
