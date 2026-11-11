from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.usage_metrics import validate_date_range


def test_usage_metric_range_accepts_inclusive_single_day():
    validate_date_range(date(2026, 1, 1), date(2026, 1, 1))


def test_usage_metric_range_rejects_reverse_and_unbounded_ranges():
    with pytest.raises(ValueError):
        validate_date_range(date(2026, 2, 1), date(2026, 1, 1))
    with pytest.raises(ValueError):
        validate_date_range(date(2020, 1, 1), date(2031, 1, 1))


async def test_usage_metric_endpoint_includes_zero_catalog_and_unassigned():
    from app.api.admin import usage_metrics
    current = MagicMock(); current.id = 1; current.name = "Africorp"; current.is_selectable = True
    historical = MagicMock(); historical.id = 2; historical.name = "Former BU"; historical.is_selectable = False
    db = AsyncMock()
    db.scalars = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[current, historical])))
    db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[
        (date(2026, 1, 2), 1, 3), (date(2026, 1, 3), None, 1),
    ])))
    result = await usage_metrics(date(2026, 1, 1), date(2026, 1, 3), db=db, _upn="admin@taxconsulting.co.za")
    assert result["metric"] == "action_items"
    assert [row["name"] for row in result["groups"]] == ["Africorp", "Former BU", "Unassigned"]
    assert result["days"] == [
        {"date": "2026-01-01", "counts": {}},
        {"date": "2026-01-02", "counts": {"1": 3}},
        {"date": "2026-01-03", "counts": {"unassigned": 1}},
    ]


@pytest.mark.parametrize("metric", ["meetings"])
async def test_usage_metric_endpoint_accepts_durable_created_metrics(metric):
    from app.api.admin import usage_metrics
    unit = MagicMock(); unit.id = 1; unit.name = "Africorp"; unit.is_selectable = True
    db = AsyncMock()
    db.scalars = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[unit])))
    db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[(date(2026, 1, 2), 1, 2)])))
    result = await usage_metrics(date(2026, 1, 1), date(2026, 1, 3), metric=metric, db=db, _upn="admin@taxconsulting.co.za")
    assert result["metric"] == metric
    assert result["days"][1]["counts"] == {"1": 2}
