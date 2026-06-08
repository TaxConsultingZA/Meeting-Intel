import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import select, text
from .api import webhooks, reviews, subscriptions, recordings, calendar, notifications, admin, users
from .config import get_settings
from .db import engine, SessionLocal
from .models import Base, BusinessUnit, RegisteredUser, BUSINESS_UNITS

settings = get_settings()
log = logging.getLogger("meeting_intel")

_RECONCILE_INTERVAL = 10 * 60  # 10 minutes


async def _init_db() -> None:
    """Create all tables (idempotent) and add new columns to existing tables if absent."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Safe column additions for existing deployments — IF NOT EXISTS prevents errors
        await conn.execute(text(
            "ALTER TABLE meeting_participants "
            "ADD COLUMN IF NOT EXISTS access_type VARCHAR(20) DEFAULT 'participant'"
        ))
        await conn.execute(text(
            "ALTER TABLE meetings "
            "ADD COLUMN IF NOT EXISTS attendees_raw JSONB"
        ))


async def _seed_business_units() -> None:
    """Insert pre-defined business units if they don't exist yet."""
    async with SessionLocal() as db:
        for name in BUSINESS_UNITS:
            existing = await db.scalar(select(BusinessUnit).where(BusinessUnit.name == name))
            if not existing:
                db.add(BusinessUnit(name=name))
        await db.commit()


async def _seed_admin_users() -> None:
    """Auto-register any UPNs listed in ADMIN_UPNS as admins if not already present.

    stanley@taxconsulting.co.za is always seeded as a permanent admin regardless of
    ADMIN_UPNS — no env var required.
    """
    # stanley is always an admin — hardcoded so no env config is needed
    permanent_admins = {"stanley@taxconsulting.co.za"}
    extra_admins = {u.strip().lower() for u in settings.admin_upns if u.strip()}
    all_admins = permanent_admins | extra_admins

    async with SessionLocal() as db:
        for upn in all_admins:
            existing = await db.scalar(select(RegisteredUser).where(RegisteredUser.upn == upn))
            if not existing:
                db.add(RegisteredUser(upn=upn, is_admin=True))
                log.info("Bootstrapped admin user: %s", upn)
        await db.commit()


async def _reconcile_loop() -> None:
    """Background loop: scan every registered user's OneDrive and auto-import new recordings.

    Waits 30 seconds after startup to let the app and DB pool finish initialising,
    then runs ``reconcile()`` every ``_RECONCILE_INTERVAL`` seconds.  Errors are
    logged and swallowed so a transient Graph API failure never kills the server.
    """
    await asyncio.sleep(30)  # let the app finish starting up first
    while True:
        try:
            from workers.reconcile import reconcile
            found = await reconcile()
            if found:
                log.info("Auto-reconcile: processed %d new recording(s)", found)
        except Exception as exc:
            log.warning("Auto-reconcile error (will retry): %s", exc)
        await asyncio.sleep(_RECONCILE_INTERVAL)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """FastAPI lifespan: initialise DB, seed reference data, then start the reconcile loop."""
    await _init_db()
    await _seed_business_units()
    await _seed_admin_users()
    task = asyncio.create_task(_reconcile_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="Meeting Intelligence", lifespan=_lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"error": "Invalid request"})


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhooks.router, tags=["webhooks"])
app.include_router(reviews.router, tags=["reviews"])
app.include_router(subscriptions.router, tags=["subscriptions"])
app.include_router(recordings.router, tags=["recordings"])
app.include_router(calendar.router, tags=["calendar"])
app.include_router(notifications.router, tags=["notifications"])
app.include_router(admin.router)
app.include_router(users.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/reconcile")
async def trigger_reconcile(x_reconcile_secret: str = Header(...)):
    """Called by GitHub Actions every 15 minutes to process new recordings."""
    settings = get_settings()
    if not settings.reconcile_secret or x_reconcile_secret != settings.reconcile_secret:
        raise HTTPException(status_code=401, detail="Invalid secret")

    # Run in background so the HTTP response returns immediately
    async def _run():
        from workers.reconcile import reconcile
        await reconcile()

    asyncio.create_task(_run())
    return {"status": "reconciliation started"}
