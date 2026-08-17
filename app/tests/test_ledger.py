"""Tests for app/services/ledger.py — claim_item idempotency gate."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestClaimItem:
    async def test_new_item_returns_true(self):
        from app.services.ledger import claim_item

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.scalar.return_value = None  # item not seen before

        result = await claim_item(mock_db, "drive-item-1", "drive-1", etag="abc", source="reconcile")

        assert result is True
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    async def test_existing_item_returns_false(self):
        from app.services.ledger import claim_item

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.scalar.return_value = MagicMock()  # already exists

        result = await claim_item(mock_db, "drive-item-1", "drive-1", etag="abc", source="reconcile")

        assert result is False
        mock_db.add.assert_not_called()
        mock_db.commit.assert_not_called()

    async def test_source_webhook_accepted(self):
        from app.services.ledger import claim_item

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.scalar.return_value = None

        result = await claim_item(mock_db, "item-2", "drive-2", etag=None, source="webhook")
        assert result is True

    async def test_null_drive_id_accepted(self):
        from app.services.ledger import claim_item

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.scalar.return_value = None

        result = await claim_item(mock_db, "item-3", None, etag=None, source="manual")
        assert result is True

    async def test_concurrent_unique_insert_is_treated_as_duplicate(self):
        from sqlalchemy.exc import IntegrityError
        from app.services.ledger import claim_item

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.scalar.return_value = None
        mock_db.commit.side_effect = IntegrityError("insert", {}, RuntimeError("duplicate"))

        result = await claim_item(
            mock_db, "same-item", "drive-1", etag=None, source="reconcile"
        )

        assert result is False
        mock_db.rollback.assert_awaited_once()
