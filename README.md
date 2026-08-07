# Meeting Intelligence

Opt-in meeting pipeline: a company user signs in with Microsoft Entra, subscribes
once, and the background worker syncs that user's Outlook calendar and OneDrive
Recordings folder. New recordings are transcribed and saved for review. Structured
AI notes are intentionally disabled until the company selects a provider. The organiser
reviews the result, chooses the exact email
recipients, and approves before any notes are sent.

## Architecture

```
Microsoft Entra access token
        │  signature + tenant + audience + scope validation
        ▼
Explicit user opt-in (is_subscribed)
        │
        ├────────► Outlook Calendar cache
        │
        ▼
OneDrive Recordings (subscribed users only)
        │
        ▼
Microsoft sync worker (runs every 10 min)
        │  walks only opted-in users' Recordings/ folders
        │  deduplication ledger prevents re-processing
        ▼
Download MP4 ─► AssemblyAI transcription (diarized, speaker-labelled)
        │
        ▼
Transcript-only completion (no language-model call)
        │
        ▼
Postgres (meetings · action_items · participants · processed_items)
        │
        ▼
Organiser-only approval gate
        │  organiser selects recipients with checkboxes
        ▼
Email sent via Graph sendMail
  → only the explicitly selected meeting attendees
  → Tax Consulting branded HTML template
```

## Key design decisions

- **Verified identity** — the API rejects the old `x-user-upn` header and accepts
  only an Entra bearer token issued for this API.
- **Stable authorization identity** — the verified Entra `oid` is bound to the
  user record; mutable email/username claims are not the permanent identity key.
- **Explicit opt-in** — sign-in alone does not grant processing consent.
- **Least data access** — reconciliation and webhooks ignore non-subscribed users.
- **AssemblyAI** for diarized transcription (speaker labels, no ffmpeg needed — accepts MP4 directly).
- **Transcript-only review** after AssemblyAI; structured extraction remains disabled until an AI provider is approved.
- **organizer_upn fallback** — uses drive-owner UPN when SharePoint App is listed as creator.
- **POPIA notice** fires before any AI processing (Section 18 compliance).
- **Row-level access** — a user sees a meeting only if they appear in `meeting_participants`.
- **Organiser approval** — participants may view meetings they can access, but only
  the organiser can edit action items and approve.
- **Custom distribution** — approval records the exact selected recipient list,
  approving user, and timestamp.

## Microsoft Entra production setup

Use two app registrations:

1. **Meeting Intelligence API**
   - Expose `api://<API-CLIENT-ID>/access_as_user`.
   - Add Microsoft Graph **application** permissions required by the background
     worker: `Calendars.ReadBasic` (or `Calendars.Read` if more event fields are
     required), `Files.Read.All`, and `Mail.Send` only when email delivery is enabled.
   - Grant tenant admin consent.
   - Prefer Exchange/SharePoint application access controls so the service can
     reach only the intended mailboxes and sites.
2. **Meeting Intelligence Web**
   - Configure the NextAuth callback URL:
     `https://<your-host>/api/auth/callback/microsoft-entra-id`.
   - Add delegated access to the API's `access_as_user` scope.

Backend:

```env
AUTH_MODE=entra
TENANT_ID=<tenant-guid>
CLIENT_ID=<api-client-id>
CLIENT_SECRET=<api-client-secret>
ENTRA_API_AUDIENCE=<api-client-id>
ENTRA_REQUIRED_SCOPE=access_as_user
GRAPH_IMPL=microsoft
```

Frontend:

```env
AUTH_MICROSOFT_ENTRA_ID_ID=<web-client-id>
AUTH_MICROSOFT_ENTRA_ID_SECRET=<web-client-secret>
AUTH_MICROSOFT_ENTRA_ID_TENANT_ID=<tenant-guid>
AUTH_MICROSOFT_ENTRA_ID_API_ID=<api-client-id>
NEXT_PUBLIC_AUTH_MODE=entra
```

The frontend requests a token specifically for the Meeting Intelligence API.
A Microsoft Graph token must not be accepted by this API because its `aud`
claim names a different resource.

## Environment Setup

The project requires environment variables in two locations:

### 1. Root `.env` (Backend & Shared)
Copy `.env.example` to `.env` in the root directory. This file is used by:
- **FastAPI Backend:** For DB connections and AI services.
- **Next.js Frontend:** For shared variables (DB, Auth).

### 2. Frontend `.env.local` (Optional Override)
You can also create `frontend/.env.local` specifically for frontend-only variables. See `frontend/.env.example`.

### Required Variables Checklist
- [ ] **Microsoft Entra ID:** `TENANT_ID`, `CLIENT_ID`, `CLIENT_SECRET` (Get from Azure Portal)
- [ ] **Auth Secret:** `AUTH_SECRET` (Generate with `npx auth secret`)
- [ ] **Database:** `DATABASE_URL` (Ensure port 5434 matches Docker)
- [ ] **Transcription:** `ASSEMBLYAI_API_KEY`

## Safe automated tests

The test suite forces Mock Graph, transcription, and extraction internally so it
cannot consume paid API quota. The interactive application uses Microsoft Entra
only; there is no Demo/Hybrid email login.

For test-only backend processes, use:

   ```env
   TENANT_ID=mock-tenant
   CLIENT_ID=mock-client
   CLIENT_SECRET=mock-secret
   AUTH_MODE=mock
   DATABASE_URL=postgresql+asyncpg://meeting:meeting@localhost:5434/meeting_intel
   GRAPH_IMPL=mock
   TRANSCRIBER_IMPL=mock
   EXTRACTOR_IMPL=mock
   EMAILS_ENABLED=false
   POPIA_NOTICE_ENABLED=false
   ENABLE_AUTO_RECONCILE=false
   AUTO_SEND_EMAIL=false
   ```

Create the Python environment and install backend/test dependencies:

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
   ```

4. Start and initialise PostgreSQL:

   ```powershell
   docker compose up -d db
   .\.venv\Scripts\python.exe -m alembic upgrade head
   docker cp frontend/auth-tables.sql meeting-intel-db-1:/tmp/auth-tables.sql
   docker compose exec -T db psql -U meeting -d meeting_intel -f /tmp/auth-tables.sql
   ```

5. Install the frontend and run all automated checks:

   ```powershell
   cd frontend
   npm ci
   npm test
   npm run build
   cd ..
   .\.venv\Scripts\python.exe -m pytest
   ```

6. Start the backend and frontend in two terminals:

   ```powershell
   # Terminal 1, repository root
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

   # Terminal 2, frontend directory
   npm run dev
   ```

7. Open `http://localhost:3000`, use `demo.user@taxconsulting.co.za`
   with the Local Mock login, click the one-time subscription button, then
   import `Quarterly Planning Demo.mp4`.

Never enable Mock mode in production. Production must use verified Microsoft Entra
authentication and real secret management.

### Webhooks (optional — reconciliation covers this)

Graph must reach your machine over HTTPS. Use `ngrok http 8000`, set `WEBHOOK_BASE_URL`,
then `POST /subscriptions/ensure` to register subscriptions for opted-in users only.

## Azure production deployment

### Prerequisites

- Azure CLI installed and logged in (`az login`)
- Docker Desktop running

### One-time resource setup

```bash
# Variables — change these
RG=meeting-intel-rg
LOCATION=southafricanorth
ACR=meetingintelacr
APP_ENV=meeting-intel-env
API_APP=meeting-intel-api
JOB_NAME=meeting-intel-reconcile
PG_SERVER=meeting-intel-pg
PG_DB=meeting_intel
PG_USER=meeting
PG_PASS=<choose-a-strong-password>

# Resource group
az group create --name $RG --location $LOCATION

# Container Registry
az acr create --name $ACR --resource-group $RG --sku Basic --admin-enabled true

# PostgreSQL Flexible Server
az postgres flexible-server create \
  --name $PG_SERVER --resource-group $RG --location $LOCATION \
  --admin-user $PG_USER --admin-password $PG_PASS \
  --sku-name Standard_B1ms --tier Burstable \
  --public-access 0.0.0.0

az postgres flexible-server db create \
  --server-name $PG_SERVER --resource-group $RG --database-name $PG_DB

# Container Apps environment
az containerapp env create --name $APP_ENV --resource-group $RG --location $LOCATION
```

### Build and push image

```bash
az acr login --name $ACR
docker build -t $ACR.azurecr.io/meeting-intel:latest .
docker push $ACR.azurecr.io/meeting-intel:latest
```

### Deploy the API

```bash
az containerapp create \
  --name $API_APP --resource-group $RG \
  --environment $APP_ENV \
  --image $ACR.azurecr.io/meeting-intel:latest \
  --registry-server $ACR.azurecr.io \
  --target-port 8000 --ingress external \
  --min-replicas 1 --max-replicas 2 \
  --env-vars \
    AUTH_MODE=entra TENANT_ID=<> CLIENT_ID=<> CLIENT_SECRET=<> \
    ENTRA_API_AUDIENCE=<> ENTRA_REQUIRED_SCOPE=access_as_user \
    ALLOWED_DOMAIN=taxconsulting.co.za \
    DATABASE_URL=postgresql+asyncpg://$PG_USER:$PG_PASS@$PG_SERVER.postgres.database.azure.com/$PG_DB \
    ASSEMBLYAI_API_KEY=<> \
    TRANSCRIBER_IMPL=assemblyai EXTRACTOR_IMPL=transcript_only \
    EMAILS_ENABLED=false POPIA_NOTICE_ENABLED=true ENABLE_AUTO_RECONCILE=false \
    MAIL_SENDER_UPN=<> WEBHOOK_CLIENT_STATE=<>
```

### Deploy the reconciliation job (runs every 15 minutes)

```bash
az containerapp job create \
  --name $JOB_NAME --resource-group $RG \
  --environment $APP_ENV \
  --image $ACR.azurecr.io/meeting-intel:latest \
  --registry-server $ACR.azurecr.io \
  --trigger-type Schedule \
  --cron-expression "*/15 * * * *" \
  --replica-timeout 600 \
  --command "python" --args "-m" "app.workers.reconcile" \
  --env-vars \
    AUTH_MODE=entra TENANT_ID=<> CLIENT_ID=<> CLIENT_SECRET=<> \
    ALLOWED_DOMAIN=taxconsulting.co.za \
    DATABASE_URL=postgresql+asyncpg://$PG_USER:$PG_PASS@$PG_SERVER.postgres.database.azure.com/$PG_DB \
    ASSEMBLYAI_API_KEY=<> \
    TRANSCRIBER_IMPL=assemblyai EXTRACTOR_IMPL=transcript_only \
    EMAILS_ENABLED=false POPIA_NOTICE_ENABLED=true \
    MAIL_SENDER_UPN=<>
```

### Run migrations on first deploy

```bash
az containerapp exec --name $API_APP --resource-group $RG \
  --command "alembic upgrade head"
```

### Set WEBHOOK_BASE_URL after deploy

```bash
# Get the API URL
API_URL=$(az containerapp show --name $API_APP --resource-group $RG \
  --query properties.configuration.ingress.fqdn -o tsv)

az containerapp update --name $API_APP --resource-group $RG \
  --set-env-vars WEBHOOK_BASE_URL=https://$API_URL

# Register or renew webhook subscriptions for opted-in users
curl -X POST https://$API_URL/subscriptions/ensure
```

## Environment variables reference

| Variable | Required | Description |
| --- | --- | --- |
| `TENANT_ID` | Yes | Entra tenant ID |
| `CLIENT_ID` | Yes | App registration client ID |
| `CLIENT_SECRET` | Yes | App registration secret |
| `AUTH_MODE` | Yes | `entra` in production; `mock` only for local Mock mode |
| `ENTRA_API_AUDIENCE` | Yes | Client ID expected in the API access token `aud` claim |
| `ENTRA_REQUIRED_SCOPE` | No | Default: `access_as_user` |
| `ALLOWED_DOMAIN` | Yes | e.g. `taxconsulting.co.za` |
| `DATABASE_URL` | Yes | asyncpg connection string |
| `ASSEMBLYAI_API_KEY` | Yes | AssemblyAI key |
| `TRANSCRIBER_IMPL` | No | `assemblyai` or `mock` |
| `EXTRACTOR_IMPL` | No | `transcript_only` now; `azure_openai` after a provider is approved; `mock` in tests |
| `MAIL_SENDER_UPN` | Yes | Mailbox emails send from |
| `AUTO_SEND_EMAIL` | No | Deprecated; explicit organiser approval is the send gate |
| `POPIA_NOTICE_ENABLED` | No | `true` to send POPIA notice before processing |
| `WEBHOOK_BASE_URL` | No | Public HTTPS URL for Graph webhook delivery |
| `WEBHOOK_CLIENT_STATE` | No | Random string to verify webhook authenticity |
