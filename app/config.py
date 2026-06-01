from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Microsoft Graph / Entra app registration (you have these) ---
    tenant_id: str
    client_id: str
    client_secret: str
    graph_scope: str = "https://graph.microsoft.com/.default"
    graph_base: str = "https://graph.microsoft.com/v1.0"

    # Restrict logins / processing to your domain
    allowed_domain: str = "taxconsulting.co.za"

    # Public HTTPS URL Graph will POST notifications to (ngrok in dev)
    webhook_base_url: str = "https://localhost:8000"
    # Random secret you generate; Graph echoes it back so you can verify notifications
    webhook_client_state: str = "change-me-to-a-random-string"

    # --- Azure Service Bus ---
    servicebus_connection_string: str = ""
    servicebus_queue_name: str = "meeting-jobs"

    # --- Database ---
    # Accepts Railway's postgres:// or postgresql:// and normalises to asyncpg driver
    database_url: str = "postgresql+asyncpg://meeting:meeting@localhost:5432/meeting_intel"

    @property
    def asyncpg_url(self) -> str:
        url = self.database_url
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                url = "postgresql+asyncpg://" + url[len(prefix):]
                break
        return url

    # --- AI layer ---
    transcriber_impl: str = "assemblyai"    # mock | assemblyai
    extractor_impl: str = "anthropic"       # mock | anthropic | azure_openai

    assemblyai_api_key: str = ""

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    # Azure OpenAI (optional fallback)
    azure_openai_endpoint: str = ""
    azure_openai_key: str = ""
    azure_openai_deployment: str = "gpt-4o"

    # UPN of the shared mailbox / service account used to send all outbound mail.
    # The Entra app must have Mail.Send delegated or application permission for this account.
    mail_sender_upn: str = ""

    # --- Behaviour ---
    auto_send_email: bool = False           # v1: humans approve before send
    popia_notice_enabled: bool = True       # send AI-processing notice to organizer on job start


@lru_cache
def get_settings() -> Settings:
    return Settings()
