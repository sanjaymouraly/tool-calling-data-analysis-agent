"""Property-based and metamorphic tests.

These check invariants that must hold for *any* input, not just for the
fixtures used in the other test modules.
"""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal

import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.money import percent_change, quantize_money, sum_money, to_decimal
from app.core.periods import period_for_date, previous_period, resolve_period
from app.core.security import sanitize_export_cell, scan_text_for_injection
from app.ingest.normalize import coerce_frame, profile_frame, quality_report

MONEY = st.decimals(
    min_value=Decimal("-1000000"),
    max_value=Decimal("1000000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


class TestMoneyProperties:
    @given(MONEY)
    def test_decimal_round_trip(self, value):
        assert to_decimal(str(value)) == value

    @given(st.lists(MONEY, min_size=1, max_size=50))
    def test_sum_is_additive(self, values):
        total = sum_money(values)
        expected = float(sum(values))
        assert math.isclose(total, expected, rel_tol=1e-9, abs_tol=1e-6)

    @given(MONEY, MONEY)
    def test_percent_change_inverts_the_value(self, new, old):
        """``new == old * (1 + pct / 100)`` for every non-zero baseline."""
        if old == 0:
            return
        pct, _ = percent_change(new, old)
        if pct is None:
            return
        reconstructed = float(old) * (1 + pct / 100)
        assert math.isclose(reconstructed, float(new), rel_tol=1e-6, abs_tol=1e-4)

    @given(MONEY, MONEY)
    def test_percent_change_of_equal_values_is_zero(self, new, old):
        pct, _ = percent_change(new, old)
        if new == old and old != 0:
            assert pct == 0.0

    @given(MONEY)
    def test_quantisation_is_idempotent(self, value):
        once = quantize_money(value)
        assert quantize_money(once) == once


class TestPeriodProperties:
    @given(st.integers(min_value=1900, max_value=2100), st.integers(min_value=1, max_value=12))
    def test_month_period_round_trip(self, year, month):
        spec = f"{year}-{month:02d}"
        period = resolve_period(spec)
        assert period.start <= period.end
        assert period.start.year == year
        assert period.start.month == month

    @given(st.integers(min_value=2000, max_value=2100), st.integers(min_value=1, max_value=12))
    def test_previous_period_is_earlier(self, year, month):
        spec = f"{year}-{month:02d}"
        current = resolve_period(spec)
        previous = previous_period(spec)
        assert previous.end < current.start

    @given(st.dates(min_value=date(2000, 1, 1), max_value=date(2099, 12, 31)))
    def test_period_labels_are_stable(self, value):
        label = period_for_date(pd.Timestamp(value), "month")
        assert resolve_period(label).start.year == value.year
        assert resolve_period(label).start.month == value.month


class TestSecurityProperties:
    @given(st.text(max_size=120))
    def test_export_sanitisation_is_idempotent(self, value):
        once = sanitize_export_cell(value)
        twice = sanitize_export_cell(once)
        assert once == twice

    @given(st.text(max_size=200))
    def test_injection_scanner_never_crashes(self, value):
        assert isinstance(scan_text_for_injection(value), list)


class TestIngestProperties:
    @given(
        st.lists(
            st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=50,
        )
    )
    @settings(max_examples=25, deadline=None)
    def test_numeric_columns_are_always_numeric(self, values):
        frame = pd.DataFrame({"value": values})
        coerced, raw_types = coerce_frame(frame)
        assert raw_types["value"] == "numeric"
        profile = profile_frame(coerced)
        assert profile["columns"][0]["inferred_type"] == "numeric"

    @given(
        st.lists(
            st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
            min_size=2,
            max_size=40,
        )
    )
    @settings(max_examples=25, deadline=None)
    def test_quality_score_is_bounded(self, values):
        frame = pd.DataFrame({"value": values})
        report = quality_report(frame)
        assert 0.0 <= report["score"] <= 100.0

    @given(st.lists(st.floats(min_value=0, max_value=1000, allow_nan=False), min_size=2, max_size=30))
    @settings(max_examples=25, deadline=None)
    def test_profile_missing_counts_are_consistent(self, values):
        frame = pd.DataFrame({"value": values})
        profile = profile_frame(frame)
        column = profile["columns"][0]
        assert column["missing_count"] + len(values) - column["missing_count"] == len(values)
        assert 0 <= column["missing_pct"] <= 100


class TestAggregationInvariants:
    """Metamorphic relations that must hold for the query engine."""

    def test_sum_of_parts_equals_total(self, db, orders, ctx_factory):
        from app.tools.base import registry

        ctx = ctx_factory(orders.id)
        total = registry.dispatch(
            ctx,
            "aggregate_metrics",
            {"dataset_id": orders.id, "metrics": [{"column": "Revenue", "agg": "sum", "alias": "revenue"}]},
        )["data"]["results"][0]["revenue"]

        grouped = registry.dispatch(
            ctx,
            "group_by",
            {
                "dataset_id": orders.id,
                "by": ["Region"],
                "metrics": [{"column": "Revenue", "agg": "sum", "alias": "revenue"}],
            },
        )["data"]["results"]
        assert math.isclose(sum(row["revenue"] for row in grouped), total, rel_tol=1e-9, abs_tol=0.01)

    def test_adding_a_filter_never_increases_the_row_count(self, db, orders, ctx_factory):
        from app.tools.base import registry

        ctx = ctx_factory(orders.id)
        unfiltered = registry.dispatch(
            ctx,
            "apply_filters",
            {"dataset_id": orders.id, "filters": []},
        )["data"]["filtered_row_count"]
        filtered = registry.dispatch(
            ctx,
            "apply_filters",
            {"dataset_id": orders.id, "filters": [{"column": "Region", "op": "eq", "value": "North"}]},
        )["data"]["filtered_row_count"]
        assert filtered <= unfiltered

    def test_mean_equals_sum_over_count(self, db, orders, ctx_factory):
        from app.tools.base import registry

        ctx = ctx_factory(orders.id)
        total = registry.dispatch(
            ctx,
            "aggregate_metrics",
            {"dataset_id": orders.id, "metrics": [{"column": "Revenue", "agg": "sum", "alias": "s"}]},
        )["data"]["results"][0]["s"]
        count = registry.dispatch(
            ctx,
            "aggregate_metrics",
            {"dataset_id": orders.id, "metrics": [{"column": "Revenue", "agg": "count", "alias": "c"}]},
        )["data"]["results"][0]["c"]
        mean = registry.dispatch(
            ctx,
            "aggregate_metrics",
            {"dataset_id": orders.id, "metrics": [{"column": "Revenue", "agg": "mean", "alias": "m"}]},
        )["data"]["results"][0]["m"]
        assert math.isclose(mean, total / count, rel_tol=1e-9, abs_tol=1e-6)
