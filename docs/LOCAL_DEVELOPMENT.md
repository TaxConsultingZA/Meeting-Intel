# Local development

Verified against repository files on 2026-10-09. Commands below are instructions;
they were not executed for this documentation task.
Local development reference only; no private environment values are recorded.

## Prerequisites and environment

The Dockerfile uses Python 3.12; the frontend uses Node/npm and Next.js.
The repository does not pin a Node runtime version. Docker Compose provides
PostgreSQL 16. Install backend dependencies from `requirements-dev.txt` for tests
or `requirements.txt` for runtime, and frontend dependencies with `npm ci`.

Backend settings load root `.env` relative to the working directory. Use
`frontend/.env.local` for frontend settings (see `frontend/.env.example`).
The standard frontend startup/configuration has no explicit root `.env` loader;
do not rely on the root file being shared automatically, despite older README
wording. Shell-injected environment variables are another configuration option.
No environment files were created or changed for this task.

| Setting | Requirement / purpose |
| --- | --- |
| Backend `TENANT_ID`, `CLIENT_ID`, `CLIENT_SECRET` | Required settings; backend Graph/Entra application credentials |
| Backend `DATABASE_URL` | Override default port 5432 with the actual local database URL |
| Backend `AUTH_MODE=entra`, `ENTRA_API_AUDIENCE`, `ENTRA_REQUIRED_SCOPE=access_as_user` | API token validation; audience falls back to `CLIENT_ID` |
| Frontend `DATABASE_URL` | PostgreSQL connection for the Auth.js adapter |
| Frontend `AUTH_SECRET`, `AUTH_URL=http://localhost:3000` | Local session encryption and authentication URL |
| Frontend `AUTH_MICROSOFT_ENTRA_ID_ID`, `AUTH_MICROSOFT_ENTRA_ID_SECRET`, `AUTH_MICROSOFT_ENTRA_ID_TENANT_ID` | Web registration credentials and tenant |
| Frontend `AUTH_MICROSOFT_ENTRA_ID_API_ID` | API registration ID; falls back to frontend client ID |
| Frontend `NEXT_PUBLIC_API_URL=http://localhost:8000` | Browser API target; code fallback is `http://127.0.0.1:8000` |
| Backend `CORS_ORIGINS` | JSON list of allowed browser origins; default `["http://localhost:3000"]` |
| Backend `ADMIN_UPNS` | Optional initial administrator emails; bootstrap writes occur at API startup |
| Backend `ASSEMBLYAI_API_KEY` | Required for real AssemblyAI processing, not merely starting the API |
| Backend `MAIL_SENDER_UPN`, `APP_URL` | Mailbox and email-link URL when email workflows are enabled |

Backend settings also accept frontend-style aliases for tenant, client, secret
and audience; avoid supplying conflicting aliases in the backend environment.
For inspection-only local work retain `RECORDING_PROCESSING_ENABLED=false`,
`GEMINI_ENABLED=false`, `EMAILS_ENABLED=false`,
`ENABLE_AUTO_RECONCILE=false`, and `EXTRACTOR_IMPL=transcript_only`.
API startup schedules calendar sync after an initial 30-second delay, repeating
every 10 minutes, even with auto-reconcile disabled.

The AI foundation is connected at the existing extraction boundary.
`EXTRACTOR_IMPL` accepts only `transcript_only` (default; no generated insights)
or `mock` (synthetic output for isolated tests). Other values, including
`gemini`, `azure_openai` and `businessai`, fail settings validation before
processing. Legacy external credential settings do not enable these routes.
External AI integration is pending; there is no automatic provider fallback.

## Database setup notes

Compose maps host `5434` to container `5432` with database `meeting_intel`.
Supply your local credentials without recording them in documentation. URL shapes
(placeholders only; replace and URL-encode credential components):
backend `postgresql+asyncpg://<user>:<password>@localhost:5434/meeting_intel`;
frontend `postgresql://<user>:<password>@localhost:5434/meeting_intel`.
Backend normalizes `postgres://` and `postgresql://` to the asyncpg scheme;
frontend strips the asyncpg prefix. Use `localhost` for the supplied local setup:
the frontend SSL heuristic disables SSL only when the URL contains that string.

For a new, dedicated local database, the repository's setup procedures are:
Run the Python environment/install commands in the backend section first.

```powershell
# Repository root: these commands create/change local database state.
docker compose up -d db
.\.venv\Scripts\python.exe -m alembic upgrade head
# Frontend directory, after configuring .env.local:
node --env-file=.env.local migrate-auth.js
```

Alembic covers application migrations; `frontend/auth-tables.sql` supplies
Auth.js adapter tables through `migrate-auth.js`. The script's legacy magic-link
comment does not mean a magic-link login provider is currently enabled.
API startup itself creates tables, adds compatibility columns and seeds reference
data/admins. Point local processes only at a database intended for development.
None of these database operations were performed for this documentation task.

## Backend startup

From the repository root, after environment and local database setup:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The health endpoint is `http://localhost:8000/health`. In a separate root terminal,
start the durable recording consumer when needed:

```powershell
.\.venv\Scripts\python.exe -m app.queue.worker
```

Starting the API alone does not consume recording jobs. The worker needs the
same database/backend configuration; processing is gated by
`RECORDING_PROCESSING_ENABLED`. Session advisory locks require a direct or
session-pooled PostgreSQL connection, rather than transaction pooling.

## Frontend startup and ports

```powershell
# From the repository root:
cd frontend
npm ci
npm run dev -- --port 3000
```

Open `http://localhost:3000`. Production-style local commands are `npm run build`
then `npm run start -- --port 3000`. Standard ports: frontend 3000, API 8000,
database host 5434/container 5432.

Port 3010 is not specified in the checked repository scripts/configuration or
existing history documents. A previous 3000/3010 incident and its resolution are
unknown. If deliberately using 3010, start with `npm run dev -- --port 3010`,
use `AUTH_URL=http://localhost:3010`, allow that exact origin in `CORS_ORIGINS`,
and register `http://localhost:3010/api/auth/callback/microsoft-entra-id`.
Keep `APP_URL` aligned if generating local email links. These are configuration
requirements for that choice, not settings changed during this review.

## Authentication local configuration

Configure a Microsoft Entra Web redirect URI exactly as
`http://localhost:3000/api/auth/callback/microsoft-entra-id`.
Expose `api://<API-CLIENT-ID>/access_as_user` and permit the Web application to
request that delegated scope. Match frontend API ID to backend audience/tenant.
The frontend requests `openid profile email offline_access` plus the API scope,
uses JWT sessions with a PostgreSQL account adapter and refreshes access tokens.
The current frontend restricts sign-in to `@taxconsulting.co.za` in source.
Backend registration and explicit subscription are separate from Microsoft login.
Current tenant registrations and redirect-URI values were not inspected.

Railway is the historical remote API/worker host; it is not needed to run these
local processes. Neon is the historical remote PostgreSQL host, separate from
Railway. Use the dedicated local Compose database for this runbook rather than
assuming a remote database is safe for local startup writes.

Backend `AUTH_MODE=mock` and mock Graph/transcriber/extractor implementations
are for isolated tests. There is no current frontend Local Mock login provider;
the old README demo-login instructions are stale. Graph webhooks require a
reachable HTTPS `WEBHOOK_BASE_URL` and matching client-state secret; local HTTP
alone cannot receive Microsoft's webhook callbacks.

## Sources

`app/config.py`, `app/main.py`, `app/db.py`, `app/queue/worker.py`, `Dockerfile`,
`docker-compose.yml`, dependency manifests, `.env.example`,
`frontend/.env.example`, `frontend/src/lib/auth.ts`, `frontend/src/lib/api.ts`,
`frontend/next.config.ts`, `frontend/migrate-auth.js`, `frontend/auth-tables.sql`,
and `README.md` (checked against current source).
