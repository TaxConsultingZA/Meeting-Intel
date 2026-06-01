import asyncio
from fastapi import FastAPI, Header, HTTPException
from .api import webhooks, reviews, subscriptions
from .config import get_settings

app = FastAPI(title="Meeting Intelligence")
app.include_router(webhooks.router, tags=["webhooks"])
app.include_router(reviews.router, tags=["reviews"])
app.include_router(subscriptions.router, tags=["subscriptions"])


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
