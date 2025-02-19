"""Tests for the benchmark runner itself."""

from __future__ import annotations

import json

from app.evaluation.fixtures import FIXTURES, get_fixture
from app.evaluation.runner import attach_reference_values, run_evaluation, write_report


def test_fixtures_are_unique_and_described():
    ids = [fixture.id for fixture in FIXTURES]
    assert len(ids) == len(set(ids))
    assert all(fixture.question and fixture.dataset for fixture in FIXTURES)


def test_get_fixture():
    assert get_fixture("monthly-sales").dataset == "retail_orders"
    try:
        get_fixture("nope")
    except KeyError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected KeyError")


def test_reference_values_are_attached():
    reference = {
        "retail_orders": {"revenue_total": 100.0, "last_month_revenue": 10.0, "monthly_periods": 2},
        "supplier_deliveries": {"worst_supplier": "S1", "worst_supplier_on_time_pct": 50.0},
        "customers": {"churn_rate": 12.5},
    }
    fixtures = attach_reference_values(list(FIXTURES), reference)
    total = next(f for f in fixtures if f.id == "total-revenue")
    assert total.expected_values
    metric, expected, tolerance = total.expected_values[0]
    assert metric == "kpi_value"
    assert expected == 100.0
    assert tolerance == 0.01


def test_evaluation_runs_and_passes(db):
    report = run_evaluation("free", db=db)
    assert report.total == len(FIXTURES)
    assert report.failed == 0, [r for r in report.results if r.status != "pass"]
    assert report.pass_rate == 100.0
    for result in report.results:
        assert result.tools_match
        assert result.citation_complete
        assert result.latency_ms >= 0
        assert result.provider == "free"


def test_evaluation_report_is_serialisable(db, tmp_path):
    report = run_evaluation("free", db=db)
    path = write_report(report, tmp_path / "report.json")
    payload = json.loads(path.read_text())
    assert payload["total"] == len(FIXTURES)
    assert payload["results"]
    assert "notes" in payload
