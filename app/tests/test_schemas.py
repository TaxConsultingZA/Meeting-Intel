"""Tests for app/schemas.py — Pydantic model validation and field sync."""
import pytest
from app.schemas import ExtractedActionItem, ActionItemEdit, RichExtractionResult
from app.models import Confidence


class TestExtractedActionItemSync:
    def test_task_synced_from_action(self):
        item = ExtractedActionItem(action="Do the thing")
        assert item.task == "Do the thing"

    def test_owner_synced_from_assigned_to(self):
        item = ExtractedActionItem(action="X", assigned_to="Alice")
        assert item.owner == "Alice"

    def test_deadline_text_synced_from_due_date(self):
        item = ExtractedActionItem(action="X", due_date="end of June")
        assert item.deadline_text == "end of June"

    def test_existing_task_not_overwritten(self):
        item = ExtractedActionItem(action="New", task="Old")
        assert item.task == "Old"

    def test_default_confidence_is_medium(self):
        item = ExtractedActionItem(action="X")
        assert item.confidence == Confidence.medium

    def test_all_optional_fields_default_none(self):
        item = ExtractedActionItem(action="X")
        assert item.assigned_to is None
        assert item.department is None
        assert item.source_quote is None


class TestActionItemEdit:
    def test_all_fields_optional(self):
        edit = ActionItemEdit()
        assert edit.task is None
        assert edit.owner is None
        assert edit.deadline_iso is None
        assert edit.confidence is None

    def test_partial_update_only_task(self):
        edit = ActionItemEdit(task="Updated task")
        dumped = edit.model_dump(exclude_unset=True)
        assert dumped == {"task": "Updated task"}


class TestRichExtractionResult:
    def test_defaults_are_empty(self):
        r = RichExtractionResult()
        assert r.objective == ""
        assert r.attendees == []
        assert r.action_items == []
        assert r.next_meeting is None

    def test_platform_default(self):
        r = RichExtractionResult()
        assert r.platform == "Microsoft Teams"
