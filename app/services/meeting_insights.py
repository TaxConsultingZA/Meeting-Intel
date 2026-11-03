"""Offline adapter boundary; no network, provider registry or keys."""
import re
from typing import Protocol
class InsightsAdapter(Protocol):
    async def analyze(self, transcript: str) -> dict: ...
class MockInsightsAdapter:
    async def analyze(self, transcript: str) -> dict:
        lines = [x.strip() for x in re.split(r"[\n。！？]+", transcript) if x.strip()]
        def candidates(pattern):
            return [{"text": line, "source_quote": line, "owner": None, "deadline": None,
                     "status": "pending_confirmation"} for line in lines if re.search(pattern, line, re.I)][:30]
        return {"summary": "[MOCK / 待审核] " + " / ".join(lines[:3]),
                "actions": candidates(r"\b(will|todo|action|please)\b|需要|请|负责|跟进"),
                "decisions": candidates(r"\b(decid|agree|approv)|决定|同意|决策")}
adapter: InsightsAdapter = MockInsightsAdapter()
