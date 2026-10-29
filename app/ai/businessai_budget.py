"""Single-host preparation ledger. No transcript, key, or response bodies.

Every send consumes a reservation, even on cancellation or unknown usage. This
is a local admission limit, not a vendor billing guarantee or a distributed store.
"""
import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .contracts import FailureCode
from .providers import ProviderFailure


class UsageLedger:
    def __init__(self, path: str):
        if not path or not Path(path).is_absolute():
            raise ProviderFailure(FailureCode.CONFIGURATION)
        self.path = path

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=1)
        try:
            db.execute("""CREATE TABLE IF NOT EXISTS calls (
                fingerprint TEXT PRIMARY KEY, month TEXT NOT NULL,
                reserved INTEGER NOT NULL, status TEXT NOT NULL,
                prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER
            )""")
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, identity: str, tokens: int, *, max_requests: int, max_tokens: int) -> str:
        fingerprint = hashlib.sha256(identity.encode()).hexdigest()
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                # Unknown/malformed successful usage and exceeded bounds need
                # operator reconciliation before any subsequent send.
                blocked = db.execute("SELECT 1 FROM calls WHERE status IN ('usage_unknown','over_limit') LIMIT 1").fetchone()
                count, used = db.execute("SELECT COUNT(*), COALESCE(SUM(reserved),0) FROM calls WHERE month=?", (month,)).fetchone()
                duplicate = db.execute("SELECT 1 FROM calls WHERE fingerprint=?", (fingerprint,)).fetchone()
                if blocked or duplicate or count >= max_requests or used + tokens > max_tokens:
                    raise ProviderFailure(FailureCode.CONFIGURATION)
                db.execute("INSERT INTO calls VALUES (?,?,?,'reserved',NULL,NULL,NULL)", (fingerprint, month, tokens))
            return fingerprint
        except (sqlite3.Error, OSError):
            raise ProviderFailure(FailureCode.CONFIGURATION) from None

    def record(self, fingerprint: str, usage: dict | None, *, reserved: int, output_limit: int):
        valid = isinstance(usage, dict) and all(
            type(usage.get(k)) is int and usage[k] >= 0
            for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')
        )
        if valid:
            valid = usage['total_tokens'] == usage['prompt_tokens'] + usage['completion_tokens']
        status = 'usage_unknown' if not valid else (
            'over_limit' if usage['total_tokens'] > reserved or usage['completion_tokens'] > output_limit else 'reported'
        )
        values = tuple(usage[k] for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')) if valid else (None, None, None)
        try:
            with self._connect() as db:
                db.execute("UPDATE calls SET status=?,prompt_tokens=?,completion_tokens=?,total_tokens=? WHERE fingerprint=?",
                           (status, *values, fingerprint))
        except (sqlite3.Error, OSError):
            raise ProviderFailure(FailureCode.CONFIGURATION) from None
        if status != 'reported':
            raise ProviderFailure(FailureCode.INVALID_OUTPUT) from None
