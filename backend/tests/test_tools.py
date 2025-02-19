"""Tests for the restricted tool library, including KPI accuracy."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.core.errors import SecurityError, ToolExecutionError, ValidationError
from app.db.models import ApprovedJoin
from app.tools.base import ToolContext, registry


@pytest.fixture()
def ctx(db, orders) -> ToolContext:
    return ToolContext(db=db, settings=settings, authorized_dataset_ids=(orders.id,))


def run(ctx: ToolContext, tool: str, arguments: dict) -> dict:
    return registry.dispatch(ctx, tool, arguments)


class TestRegistry:
    def test_tool_count_is_fixed(self):
        assert len(registry.names()) == 19
        assert "compute_kpi" in registry.names()
        assert "generate_chart" in registry.names()
        assert "join_approved_datasets" in registry.names()

    def test_every_tool_has_a_schema(self):
        for definition in registry.definitions():
            assert definition["name"]
            assert definition["description"]
            assert definition["input_schema"]["type"] == "object"

    def test_unknown_tool_is_rejected(self, ctx):
        with pytest.raises(SecurityError):
            run(ctx, "exec_python", {"code": "import os"})

    def test_extra_arguments_are_rejected(self, ctx, orders):
        with pytest.raises((ValidationError, SecurityError)):
            run(ctx, "inspect_schema", {"dataset_id": orders.id, "sql": "SELECT 1"})

    def test_code_arguments_are_rejected(self, ctx, orders):
        for key in ("code", "python", "shell", "command", "path", "url"):
            with pytest.raises(SecurityError):
                run(ctx, "apply_filters", {"dataset_id": orders.id, key: "x"})


class TestDiscoveryTools:
    def test_inspect_schema(self, ctx, orders):
        data = run(ctx, "inspect_schema", {"dataset_id": orders.id})["data"]
        assert data["row_count"] == 5018
        names = {c["name"] for c in data["columns"]}
        assert "Revenue" in names and "Order_Date" in names

    def test_preview_rows_is_bounded(self, ctx, orders):
        data = run(ctx, "preview_rows", {"dataset_id": orders.id, "limit": 5})["data"]
        assert len(data["rows"]) == 5
        assert data["total_rows"] == 5018

    def test_profile_data(self, ctx, orders):
        data = run(ctx, "profile_data", {"dataset_id": orders.id})["data"]
        assert "Revenue" in data["numeric_summary"]
        assert "min" in data["numeric_summary"]["Revenue"]

    def test_check_data_quality(self, ctx, orders):
        data = run(ctx, "check_data_quality", {"dataset_id": orders.id})["data"]
        assert 0 <= data["score"] <= 100
        assert data["duplicates"]["count"] > 0


class TestFiltering:
    def test_filter_by_equality(self, ctx, orders):
        data = run(
            ctx,
            "apply_filters",
            {
                "dataset_id": orders.id,
                "filters": [{"column": "Region", "op": "eq", "value": "North"}],
            },
        )["data"]
        assert data["filtered_row_count"] > 0
        assert data["filtered_row_count"] < data["original_row_count"]
        assert all(row["Region"] == "North" for row in data["rows"])

    def test_filter_by_null(self, ctx, orders):
        data = run(
            ctx,
            "apply_filters",
            {"dataset_id": orders.id, "filters": [{"column": "Region", "op": "is_null"}]},
        )["data"]
        assert data["filtered_row_count"] > 0
        assert all(row["Region"] is None for row in data["rows"])

    def test_filter_unknown_column_is_rejected(self, ctx, orders):
        with pytest.raises(ValidationError):
            run(
                ctx,
                "apply_filters",
                {"dataset_id": orders.id, "filters": [{"column": "Nope", "op": "eq", "value": 1}]},
            )

    def test_filter_injection_payload_is_treated_as_data(self, ctx, orders):
        payload = "'; DROP TABLE datasets; --"
        data = run(
            ctx,
            "apply_filters",
            {"dataset_id": orders.id, "filters": [{"column": "Region", "op": "eq", "value": payload}]},
        )["data"]
        assert data["filtered_row_count"] == 0

    def test_contains_is_escaped(self, ctx, orders):
        data = run(
            ctx,
            "apply_filters",
            {
                "dataset_id": orders.id,
                "filters": [{"column": "Product_Name", "op": "contains", "value": "%"}],
            },
        )["data"]
        assert data["filtered_row_count"] == 0


class TestAggregation:
    def test_aggregate_sum_matches_reference(self, ctx, orders, reference_values):
        data = run(
            ctx,
            "aggregate_metrics",
            {
                "dataset_id": orders.id,
                "metrics": [{"column": "Revenue", "agg": "sum", "alias": "revenue"}],
            },
        )["data"]
        assert data["results"][0]["revenue"] == pytest.approx(
            reference_values["retail_orders"]["revenue_total"], abs=0.01
        )

    def test_group_by_matches_reference(self, ctx, orders, reference_values):
        data = run(
            ctx,
            "group_by",
            {
                "dataset_id": orders.id,
                "by": ["Product_Name"],
                "metrics": [{"column": "Revenue", "agg": "sum", "alias": "revenue"}],
                "sort_by": "revenue",
                "sort_dir": "desc",
                "limit": 5,
            },
        )["data"]
        assert data["results"][0]["Product_Name"] == reference_values["retail_orders"]["top_product"]
        assert data["results"][0]["revenue"] == pytest.approx(
            reference_values["retail_orders"]["top_product_revenue"], abs=0.01
        )

    def test_aggregation_of_unknown_column_is_rejected(self, ctx, orders):
        with pytest.raises(ValidationError):
            run(
                ctx,
                "aggregate_metrics",
                {"dataset_id": orders.id, "metrics": [{"column": "Ghost", "agg": "sum"}]},
            )

    def test_count_distinct(self, ctx, orders, reference_values):
        data = run(
            ctx,
            "aggregate_metrics",
            {
                "dataset_id": orders.id,
                "metrics": [{"column": "Order_ID", "agg": "count_distinct", "alias": "orders"}],
            },
        )["data"]
        assert data["results"][0]["orders"] == reference_values["retail_orders"]["distinct_orders"]


class TestTimeSeries:
    def test_monthly_buckets(self, ctx, orders, reference_values):
        data = run(
            ctx,
            "time_series",
            {
                "dataset_id": orders.id,
                "date_column": "Order_Date",
                "bucket": "month",
                "metrics": [{"column": "Revenue", "agg": "sum", "alias": "revenue"}],
                "include_growth": True,
            },
        )["data"]
        periods = data["periods"]
        assert len(periods) == reference_values["retail_orders"]["monthly_periods"]
        assert periods[0]["period"] == reference_values["retail_orders"]["first_month"]
        assert periods[-1]["period"] == reference_values["retail_orders"]["last_month"]
        assert periods[-1]["revenue"] == pytest.approx(
            reference_values["retail_orders"]["last_month_revenue"], abs=0.01
        )
        assert periods[-1]["growth_pct"] == pytest.approx(
            reference_values["retail_orders"]["last_month_growth_pct"], abs=0.01
        )

    def test_growth_is_undefined_for_the_first_bucket(self, ctx, orders):
        data = run(
            ctx,
            "time_series",
            {
                "dataset_id": orders.id,
                "date_column": "Order_Date",
                "bucket": "month",
                "metrics": [{"column": "Revenue", "agg": "sum", "alias": "revenue"}],
            },
        )["data"]
        assert data["periods"][0]["growth_pct"] is None
        assert "undefined" in data["periods"][0]["growth_note"]

    def test_quarterly_buckets(self, ctx, orders):
        data = run(
            ctx,
            "time_series",
            {
                "dataset_id": orders.id,
                "date_column": "Order_Date",
                "bucket": "quarter",
                "metrics": [{"column": "Revenue", "agg": "sum", "alias": "revenue"}],
            },
        )["data"]
        assert all("-Q" in p["period"] for p in data["periods"])
        assert len(data["periods"]) == 8

    def test_unknown_date_column_is_rejected(self, ctx, orders):
        with pytest.raises(ValidationError):
            run(
                ctx,
                "time_series",
                {
                    "dataset_id": orders.id,
                    "date_column": "Nope",
                    "bucket": "month",
                    "metrics": [{"column": "Revenue", "agg": "sum"}],
                },
            )


class TestKpis:
    def test_revenue_kpi(self, ctx, orders, reference_values):
        data = run(
            ctx,
            "compute_kpi",
            {"dataset_id": orders.id, "kpi": "revenue", "params": {"revenue_column": "Revenue"}},
        )["data"]
        assert data["value"] == pytest.approx(reference_values["retail_orders"]["revenue_total"], abs=0.01)
        assert data["column_resolution"]["money"]["resolution"] == "explicit"

    def test_average_order_value(self, ctx, orders, reference_values):
        data = run(
            ctx,
            "compute_kpi",
            {
                "dataset_id": orders.id,
                "kpi": "average_order_value",
                "params": {"revenue_column": "Revenue", "order_id_column": "Order_ID"},
            },
        )["data"]
        assert data["value"] == pytest.approx(
            reference_values["retail_orders"]["average_order_value"], abs=0.001
        )
        assert data["details"]["distinct_orders"] == reference_values["retail_orders"]["distinct_orders"]

    def test_gross_margin_percentage(self, ctx, orders, reference_values):
        data = run(
            ctx,
            "compute_kpi",
            {
                "dataset_id": orders.id,
                "kpi": "gross_margin_pct",
                "params": {"revenue_column": "Revenue", "cost_column": "Cost"},
            },
        )["data"]
        assert data["value"] == pytest.approx(
            reference_values["retail_orders"]["gross_margin_pct"], abs=0.001
        )

    def test_kpi_fails_when_the_columns_do_not_exist(self, db, demo_datasets):
        """A KPI whose columns cannot be resolved must fail, not invent a number."""
        customers = demo_datasets["Customers"]
        ctx = ToolContext(db=db, settings=settings, authorized_dataset_ids=(customers.id,))
        with pytest.raises(ValidationError) as excinfo:
            run(
                ctx,
                "compute_kpi",
                {"dataset_id": customers.id, "kpi": "average_order_value", "params": {}},
            )
        assert "missing_roles" in excinfo.value.details

    def test_kpi_reports_inferred_column_resolution(self, ctx, orders):
        """When a column is matched by name it must be reported as inferred."""
        data = run(ctx, "compute_kpi", {"dataset_id": orders.id, "kpi": "revenue", "params": {}})["data"]
        assert data["column_resolution"]["money"]["resolution"] == "inferred"

    def test_unknown_kpi_is_rejected(self, ctx, orders):
        with pytest.raises(ValidationError):
            run(ctx, "compute_kpi", {"dataset_id": orders.id, "kpi": "made_up_kpi"})

    def test_on_time_delivery_matches_reference(self, db, deliveries, reference_values):
        ctx = ToolContext(db=db, settings=settings, authorized_dataset_ids=(deliveries.id,))
        data = run(
            ctx,
            "compute_kpi",
            {
                "dataset_id": deliveries.id,
                "kpi": "on_time_delivery_pct",
                "params": {
                    "expected_date_column": "Expected_Date",
                    "actual_date_column": "Actual_Date",
                },
            },
        )["data"]
        assert data["value"] == pytest.approx(
            reference_values["supplier_deliveries"]["on_time_delivery_pct"], abs=0.01
        )

    def test_grouped_kpi(self, db, deliveries, reference_values):
        ctx = ToolContext(db=db, settings=settings, authorized_dataset_ids=(deliveries.id,))
        data = run(
            ctx,
            "compute_kpi",
            {
                "dataset_id": deliveries.id,
                "kpi": "on_time_delivery_pct",
                "params": {
                    "expected_date_column": "Expected_Date",
                    "actual_date_column": "Actual_Date",
                },
                "group_by": ["Supplier_Name"],
                "order": "asc",
            },
        )["data"]
        groups = data["groups"]
        assert groups[0]["group"] == reference_values["supplier_deliveries"]["worst_supplier"]
        assert groups[0]["value"] == pytest.approx(
            reference_values["supplier_deliveries"]["worst_supplier_on_time_pct"], abs=0.01
        )

    def test_churn_rate(self, db, demo_datasets):
        customers = demo_datasets["Customers"]
        ctx = ToolContext(db=db, settings=settings, authorized_dataset_ids=(customers.id,))
        data = run(
            ctx,
            "compute_kpi",
            {"dataset_id": customers.id, "kpi": "churn_rate", "params": {"churn_column": "Churned"}},
        )["data"]
        assert 0 < data["value"] < 100

    def test_sales_growth_uses_previous_period(self, ctx, orders, reference_values):
        data = run(
            ctx,
            "compute_kpi",
            {
                "dataset_id": orders.id,
                "kpi": "sales_growth",
                "params": {"revenue_column": "Revenue", "date_column": "Order_Date"},
                "period": reference_values["retail_orders"]["last_month"],
            },
        )["data"]
        assert data["value"] == pytest.approx(
            reference_values["retail_orders"]["last_month_growth_pct"], abs=0.01
        )
        assert data["details"]["current_period"]["label"] == reference_values["retail_orders"]["last_month"]


class TestRanking:
    def test_rank_categories(self, ctx, orders, reference_values):
        data = run(
            ctx,
            "rank_categories",
            {
                "dataset_id": orders.id,
                "category_column": "Product_Name",
                "metric_column": "Revenue",
                "agg": "sum",
                "top_n": 3,
            },
        )["data"]
        assert data["ranked"][0]["category"] == reference_values["retail_orders"]["top_product"]
        assert data["ranked"][0]["share_pct"] == pytest.approx(
            reference_values["retail_orders"]["top_product_share_pct"], abs=0.05
        )

    def test_bottom_n(self, ctx, orders):
        data = run(
            ctx,
            "rank_categories",
            {
                "dataset_id": orders.id,
                "category_column": "Region",
                "metric_column": "Revenue",
                "agg": "sum",
                "top_n": 2,
                "bottom_n": 2,
            },
        )["data"]
        assert len(data["bottom"]) == 2
        assert data["bottom"][0]["value"] <= data["bottom"][1]["value"]


class TestPeriodComparison:
    def test_compare_periods(self, ctx, orders):
        data = run(
            ctx,
            "compare_periods",
            {
                "dataset_id": orders.id,
                "date_column": "Order_Date",
                "metric_column": "Revenue",
                "agg": "sum",
                "period1_start": "2024-01-01",
                "period1_end": "2024-03-31",
                "period2_start": "2024-04-01",
                "period2_end": "2024-06-30",
                "group_by": ["Region"],
            },
        )["data"]
        assert data["period1"]["value"] > 0
        assert data["period2"]["value"] > 0
        assert data["percent_change"] is not None
        assert len(data["comparisons"]) >= 5  # five regions plus a missing-value group

    def test_zero_denominator_is_explicit(self, ctx, orders):
        data = run(
            ctx,
            "compare_periods",
            {
                "dataset_id": orders.id,
                "date_column": "Order_Date",
                "metric_column": "Revenue",
                "agg": "sum",
                "period1_start": "1900-01-01",
                "period1_end": "1900-01-31",
                "period2_start": "1900-02-01",
                "period2_end": "1900-02-28",
            },
        )["data"]
        assert data["percent_change"] is None
        assert "undefined" in data["percent_change_note"]


class TestStatistics:
    def test_outliers(self, ctx, orders):
        data = run(
            ctx,
            "detect_outliers",
            {"dataset_id": orders.id, "column": "Revenue", "method": "iqr", "threshold": 1.5},
        )["data"]
        assert data["outlier_count"] > 0
        assert data["bounds"]["lower"] < data["bounds"]["upper"]

    def test_correlations(self, ctx, orders):
        data = run(
            ctx,
            "compute_correlations",
            {
                "dataset_id": orders.id,
                "columns": ["Revenue", "Cost", "Quantity"],
                "method": "pearson",
            },
        )["data"]
        assert data["pairs"]
        assert all(-1.0001 <= p["correlation"] <= 1.0001 for p in data["pairs"])

    def test_distribution(self, ctx, orders):
        data = run(ctx, "compute_distribution", {"dataset_id": orders.id, "column": "Revenue", "bins": 8})[
            "data"
        ]
        assert len(data["buckets"]) == 8
        assert sum(b["count"] for b in data["buckets"]) == data["summary"]["count"]


class TestJoin:
    def test_join_requires_approval(self, ctx, orders, demo_datasets):
        customers = demo_datasets["Customers"]
        with pytest.raises(SecurityError):
            run(
                ctx,
                "join_approved_datasets",
                {
                    "left_dataset_id": orders.id,
                    "right_dataset_id": customers.id,
                    "left_key": "Customer_ID",
                    "right_key": "Customer_ID",
                },
            )

    def test_approved_join_runs(self, db, orders, demo_datasets):
        customers = demo_datasets["Customers"]
        db.add(
            ApprovedJoin(
                left_dataset_id=orders.id,
                right_dataset_id=customers.id,
                left_key="Customer_ID",
                right_key="Customer_ID",
                is_approved=True,
            )
        )
        db.commit()
        ctx = ToolContext(db=db, settings=settings, authorized_dataset_ids=(orders.id, customers.id))
        data = run(
            ctx,
            "join_approved_datasets",
            {
                "left_dataset_id": orders.id,
                "right_dataset_id": customers.id,
                "left_key": "Customer_ID",
                "right_key": "Customer_ID",
            },
        )["data"]
        assert data["result_rows"] > 0
        assert "Segment" in data["columns"]


class TestChartAndExport:
    def test_generate_chart(self, ctx, orders):
        data = run(
            ctx,
            "generate_chart",
            {
                "dataset_id": orders.id,
                "chart_type": "bar",
                "x": "Product_Name",
                "y": ["Revenue"],
                "aggregation": "sum",
                "limit": 5,
            },
        )["data"]
        spec = data["chart_spec"]
        assert spec["chart_type"] == "bar"
        assert spec["data"]
        assert len(spec["y_keys"]) == 1

    def test_chart_title_is_sanitised(self, ctx, orders):
        data = run(
            ctx,
            "generate_chart",
            {
                "dataset_id": orders.id,
                "chart_type": "bar",
                "title": "<script>alert(1)</script>Revenue",
                "x": "Region",
                "y": ["Revenue"],
            },
        )["data"]
        assert "<script>" not in data["chart_spec"]["title"]

    def test_export_sanitises_formulas(self, ctx, orders):
        formula_filter = {
            "column": "Product_Name",
            "op": "contains",
            "value": "HYPERLINK",
        }
        matched = run(
            ctx,
            "apply_filters",
            {"dataset_id": orders.id, "filters": [formula_filter], "limit": 10},
        )["data"]
        assert matched["filtered_row_count"] > 0, "the demo data contains a formula-like cell"

        exported = run(
            ctx,
            "export_results",
            {"dataset_id": orders.id, "format": "csv", "filters": [formula_filter], "limit": 10},
        )["data"]
        for row in exported["rows"]:
            assert row["Product_Name"].startswith("'=")
            assert "HYPERLINK" in row["Product_Name"]

    def test_explain_calculation(self, ctx, orders):
        data = run(
            ctx,
            "explain_calculation",
            {"dataset_id": orders.id, "calculation": "average_order_value"},
        )["data"]
        assert "COUNT(DISTINCT" in data["formula"]
        assert "order_id" in data["required_roles"]


class TestResourceLimits:
    def test_result_size_is_bounded(self, ctx, orders, monkeypatch):
        monkeypatch.setattr(settings, "max_tool_result_bytes", 512)
        with pytest.raises(ToolExecutionError):
            run(ctx, "preview_rows", {"dataset_id": orders.id, "limit": 200})

    def test_row_limit_is_bounded(self, ctx, orders, monkeypatch):
        monkeypatch.setattr(settings, "max_tool_result_rows", 3)
        with pytest.raises(ToolExecutionError):
            run(ctx, "preview_rows", {"dataset_id": orders.id, "limit": 100})
