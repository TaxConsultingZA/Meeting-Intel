from functools import lru_cache
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and the .env file.

    All fields map 1-to-1 to an env var of the same name in UPPER_SNAKE_CASE
    (e.g. ``tenant_id`` → ``TENANT_ID``).  Sensitive values (keys, secrets)
    should never be committed — keep them in .env which is git-ignored.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    # --- Microsoft Graph / Entra app registration (you have these) ---
    tenant_id: str = Field(
        validation_alias=AliasChoices(
            "AUTH_MICROSOFT_ENTRA_ID_TENANT_ID", "TENANT_ID"
        )
    )
    client_id: str = Field(
        validation_alias=AliasChoices("AUTH_MICROSOFT_ENTRA_ID_ID", "CLIENT_ID")
    )
    client_secret: str = Field(
        validation_alias=AliasChoices(
            "AUTH_MICROSOFT_ENTRA_ID_SECRET", "CLIENT_SECRET"
        )
    )
    graph_scope: str = "https://graph.microsoft.com/.default"
    graph_base: str = "https://graph.microsoft.com/v1.0"

    # Production accepts only Microsoft Entra access tokens issued for this API.
    # Mock remains available exclusively for isolated automated tests.
    auth_mode: str = "entra"  # entra | mock
    entra_api_audience: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AUTH_MICROSOFT_ENTRA_ID_API_ID", "ENTRA_API_AUDIENCE"
        ),
    )
    entra_required_scope: str = "access_as_user"

    # Restrict logins / processing to your domain
    allowed_domain: str = "taxconsulting.co.za"

    # CORS — comma-separated list of allowed origins for browser clients
    cors_origins: list[str] = ["http://localhost:3000"]

    # Public HTTPS URL Graph will POST notifications to (ngrok in dev)
    webhook_base_url: str = "https://localhost:8000"
    # Random secret you generate; Graph echoes it back so you can verify notifications
    webhook_client_state: str = "change-me-to-a-random-string"
    reconcile_secret: str = ""       # shared secret for the /reconcile endpoint
    subscription_secret: str = ""    # shared secret for the /subscriptions/ensure endpoint

    # --- Database ---
    # Accepts Railway's postgres:// or postgresql:// and normalises to asyncpg driver
    database_url: str = "postgresql+asyncpg://meeting:meeting@localhost:5432/meeting_intel"

    @property
    def asyncpg_url(self) -> str:
        """Normalise DATABASE_URL to the ``postgresql+asyncpg://`` scheme required by SQLAlchemy.

        Accepts both ``postgres://`` (Railway default) and ``postgresql://`` prefixes.
        """
        url = self.database_url
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                url = "postgresql+asyncpg://" + url[len(prefix):]
                break
        return url

    # --- AI layer ---
    graph_impl: str = "microsoft"          # microsoft | mock
    transcriber_impl: str = "assemblyai"    # mock | assemblyai
    extractor_impl: str = "transcript_only"  # transcript_only | mock | azure_openai | gemini

    # Disabled unless an administrator explicitly authorises external AI use.
    gemini_enabled: bool = False
    gemini_api_key: str = ""
    gemini_model: str = ""

    worker_poll_seconds: float = Field(default=3, gt=0)
    worker_lease_seconds: float = Field(default=120, gt=0)
    worker_heartbeat_seconds: float = Field(default=20, gt=0)
    worker_shutdown_seconds: float = Field(default=30, ge=0)

    assemblyai_api_key: str = ""

    # Azure OpenAI (optional fallback)
    azure_openai_endpoint: str = ""
    azure_openai_key: str = ""
    azure_openai_deployment: str = "gpt-4o"

    # UPN of the shared mailbox / service account used to send all outbound mail.
    # The Entra app must have Mail.Send delegated or application permission for this account.
    mail_sender_upn: str = ""

    # Public URL of the frontend — used in email links
    app_url: str = "http://localhost:3000"

    # --- Behaviour ---
    enable_auto_reconcile: bool = False     # if true, start a background task at startup to scan OneDrives
    auto_send_email: bool = False           # v1: humans approve before send
    popia_notice_enabled: bool = True       # send processing notice to organizer on job start
    emails_enabled: bool = False            # enable only after a controlled mail test

    # --- Registration ---
    # Comma-separated UPNs that are auto-registered as admins at startup.
    # Use this to bootstrap the first admin before anyone has been registered via the UI.
    admin_upns: list[str] = []

    @property
    def api_audience(self) -> str:
        """Audience expected in Entra access tokens for this FastAPI service."""
        return self.entra_api_audience or self.client_id

    @field_validator("admin_upns", mode="before")
    @classmethod
    def parse_admin_upns(cls, v: object) -> list[str]:
        """Accept comma-separated string from env or an already-parsed list."""
        if isinstance(v, list):
            return v
        if not v or not str(v).strip():
            return []
        return [u.strip() for u in str(v).split(",") if u.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return the singleton Settings instance, loading .env on first call."""
    return Settings()
