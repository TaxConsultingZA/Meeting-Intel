"""Operator-only: python -m scripts.businessai_synthetic_test. No meeting inputs.

Only run after account/model/quota verification. Never invoke from a web route,
worker, startup hook, scheduler, retry policy or deployment health check.
"""
import asyncio
import json
import os
from uuid import UUID

from pydantic import SecretStr

from app.ai.businessai import BusinessAIConfig, BusinessAIProvider, SYNTHETIC_TEXT
from app.ai.contracts import ProcessingRequest, Segment
from app.ai.providers import ProviderFailure
from app.config import get_settings


async def main():
    provider = None
    try:
        settings = get_settings()
        config = BusinessAIConfig(
            enabled=settings.businessai_enabled,
            synthetic_test_enabled=os.environ.get("BUSINESSAI_SYNTHETIC_TEST") == "confirmed-account-model-quota",
            permit_database_url=SecretStr(os.environ.get("BUSINESSAI_TEST_DATABASE_URL", "")),
            chat_url=settings.businessai_chat_url, model_id=settings.businessai_model,
            api_key=settings.businessai_api_key, ledger_path=settings.businessai_ledger_path,
            max_requests=min(settings.businessai_max_requests, 1),
            token_budget=min(settings.businessai_token_budget, 4096),
            max_output_tokens=min(settings.businessai_max_output_tokens, 256),
            max_input_bytes=min(settings.businessai_max_input_bytes, 2048),
            timeout_seconds=min(settings.businessai_timeout_seconds, 30),
        )
        provider = BusinessAIProvider(config)
        await provider.process(ProcessingRequest(
            meeting_id=UUID("00000000-0000-0000-0000-000000000001"),
            segments=(Segment(id="synthetic-1", speaker="Speaker A", text=SYNTHETIC_TEXT),),
        ))
    except Exception as error:
        # Settings/transport/database exceptions must never print raw inputs.
        code = error.code.value if isinstance(error, ProviderFailure) else "configuration"
        print(json.dumps({"status": "stopped", "failure": code,
                          "usage": getattr(provider, "reported_usage", None),
                          "retry": False}))
        return 1
    print(json.dumps({"status": "succeeded", "usage": provider.reported_usage, "retry": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
