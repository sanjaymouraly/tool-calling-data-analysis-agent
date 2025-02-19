"""API-free deterministic provider.

This provider makes the application fully usable without any credentials.
It is a rule-based analyst: the question is classified into an *intent*, the
intent is mapped onto a validated tool plan using the dataset's own schema,
and every column reference is checked against that schema before the plan is
returned.

It is intentionally conservative: when the question cannot be mapped onto a
supported analysis the provider asks for clarification instead of guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .base import BaseProvider, DatasetContext, ProviderContext, ProviderError, ProviderInfo, ProviderResult

# --------------------------------------------------------------------------- #
# Intent detection
# --------------------------------------------------------------------------- #

INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "time_series": (
        "monthly",
        "weekly",
        "daily",
        "quarterly",
        "per month",
        "by month",
        "over time",
        "trend",
        "time series",
        "historical",
        "growth rate",
        "over the months",
        "by quarter",
    ),
    "ranking": (
        "top",
        "bottom",
        "highest",
        "lowest",
        "best",
        "worst",
        "which products",
        "which categories",
        "which suppliers",
        "which customers",
        "rank",
        "leader",
        "biggest",
        "smallest",
    ),
    "period_comparison": (
        "compare",
        "versus",
        " vs ",
        "year over year",
        "yoy",
        "quarter over quarter",
        "qoq",
        "this quarter",
        "last quarter",
        "month over month",
        "mom",
    ),
    "kpi": (
        "aov",
        "average order value",
        "revenue",
        "total sales",
        "gross margin",
        "margin",
        "profit",
        "conversion rate",
        "churn",
        "retention",
        "on-time",
        "on time",
        "turnover",
        "average basket",
        "unit price",
        "discount",
    ),
    "correlation": ("correlation", "correlate", "related to", "relationship", "associated with"),
    "outliers": ("outlier", "anomal", "unusual", "spike", "weird", "extreme", "odd"),
    "quality": (
        "missing",
        "duplicate",
        "duplicated",
        "null",
        "blank",
        "empty",
        "data quality",
        "quality",
        "integrity",
    ),
    "distribution": ("distribution", "histogram", "spread", "buckets of"),
    "profile": ("describe", "profile", "overview", "summary", "statistics", "statistical"),
    "preview": ("show me rows", "first rows", "sample rows", "peek", "preview"),
    "chart": ("chart", "graph", "plot", "visualis", "visualiz", "show me a"),
    "export": ("export", "download", "csv", "xlsx", "spreadsheet of"),
    "join": ("join", "combine", "merge", "match with", "cross-reference", "cross reference"),
    "explain": ("how is", "how was", "how calculated", "explain", "definition of", "what does"),
}


@dataclass
class ColumnRoles:
    """Resolved column roles for one dataset."""

    date: str | None = None
    money: str | None = None
    cost: str | None = None
    quantity: str | None = None
    order_id: str | None = None
    customer_id: str | None = None
    product: str | None = None
    category: str | None = None
    region: str | None = None
    supplier: str | None = None
    status: str | None = None
    expected_date: str | None = None
    actual_date: str | None = None
    on_time_flag: str | None = None
    churn_flag: str | None = None
    conversion_flag: str | None = None
    inventory_on_hand: str | None = None
    unit_price: str | None = None
    discount: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "date": self.date,
            "money": self.money,
            "cost": self.cost,
            "quantity": self.quantity,
            "order_id": self.order_id,
            "customer_id": self.customer_id,
            "product": self.product,
            "category": self.category,
            "region": self.region,
            "supplier": self.supplier,
            "status": self.status,
            "expected_date": self.expected_date,
            "actual_date": self.actual_date,
            "on_time_flag": self.on_time_flag,
            "churn_flag": self.churn_flag,
            "conversion_flag": self.conversion_flag,
            "inventory_on_hand": self.inventory_on_hand,
            "unit_price": self.unit_price,
            "discount": self.discount,
        }


def _role_columns(dataset: DatasetContext) -> ColumnRoles:
    roles = ColumnRoles()
    by_role: dict[str, str] = {}
    for column in dataset.columns:
        role = column.get("role")
        if role and role not in by_role:
            by_role[role] = str(column.get("name"))
    roles.date = by_role.get("date")
    roles.money = by_role.get("money")
    roles.cost = by_role.get("cost")
    roles.quantity = by_role.get("quantity")
    roles.order_id = by_role.get("order_id")
    roles.customer_id = by_role.get("customer_id")
    roles.product = by_role.get("product_name") or by_role.get("product_id")
    roles.category = by_role.get("category") or by_role.get("product_name")
    roles.region = by_role.get("region")
    roles.supplier = by_role.get("supplier") or by_role.get("supplier_id")
    roles.status = by_role.get("status")
    roles.expected_date = by_role.get("expected_date")
    roles.actual_date = by_role.get("actual_date")
    roles.on_time_flag = by_role.get("on_time_flag")
    roles.churn_flag = by_role.get("churn_flag")
    roles.conversion_flag = by_role.get("conversion_flag")
    roles.inventory_on_hand = by_role.get("inventory_on_hand")
    roles.unit_price = by_role.get("unit_price")
    roles.discount = by_role.get("discount")
    return roles


def _bucket_for(question: str) -> str:
    lowered = question.lower()
    if "daily" in lowered or "by day" in lowered:
        return "day"
    if "weekly" in lowered or "by week" in lowered:
        return "week"
    if "quarter" in lowered or "by quarter" in lowered:
        return "quarter"
    if "yearly" in lowered or "annual" in lowered or "by year" in lowered:
        return "year"
    return "month"


def _quarter_of(month_label: str) -> str | None:
    match = re.match(r"^(\d{4})-(\d{2})$", month_label or "")
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    return f"{year}-Q{(month - 1) // 3 + 1}"


def _previous_quarter(label: str) -> str | None:
    match = re.match(r"^(\d{4})-Q([1-4])$", label or "")
    if not match:
        return None
    year, quarter = int(match.group(1)), int(match.group(2))
    if quarter == 1:
        return f"{year - 1}-Q4"
    return f"{year}-Q{quarter - 1}"


def _previous_month(label: str) -> str | None:
    match = re.match(r"^(\d{4})-(\d{2})$", label or "")
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"


def _select_kpi(
    question: str, roles: ColumnRoles, *, allow_revenue: bool = True
) -> tuple[str | None, dict[str, Any], list[str] | None, str]:
    """Choose the KPI that matches the question, if any.

    Returns ``(kpi, params, group_by, order)``.  Every parameter is an
    explicit column mapping so the KPI tool never has to guess.
    """
    params: dict[str, Any] = {}
    group_by: list[str] | None = None
    order = "asc" if ("lowest" in question or "worst" in question) else "desc"

    if (
        "average order value" in question or "aov" in question or "average basket" in question
    ) and roles.money:
        params["revenue_column"] = roles.money
        if roles.order_id:
            params["order_id_column"] = roles.order_id
        return "average_order_value", params, None, order

    if ("on-time" in question or "on time" in question or "delivery" in question) and (
        roles.expected_date and roles.actual_date
    ):
        params["expected_date_column"] = roles.expected_date
        params["actual_date_column"] = roles.actual_date
        if roles.supplier and ("supplier" in question or "vendor" in question):
            group_by = [roles.supplier]
        elif roles.region and "region" in question:
            group_by = [roles.region]
        return "on_time_delivery_pct", params, group_by, order

    if ("on-time" in question or "on time" in question) and roles.on_time_flag:
        params["on_time_flag_column"] = roles.on_time_flag
        if roles.supplier and ("supplier" in question or "vendor" in question):
            group_by = [roles.supplier]
        return "on_time_delivery_pct", params, group_by, order

    if "margin" in question and roles.money and roles.cost:
        params["revenue_column"] = roles.money
        params["cost_column"] = roles.cost
        return "gross_margin_pct", params, None, order

    if ("churn" in question) and roles.churn_flag:
        params["churn_column"] = roles.churn_flag
        return "churn_rate", params, None, order

    if ("conversion" in question) and roles.conversion_flag:
        params["conversion_column"] = roles.conversion_flag
        return "conversion_rate", params, None, order

    if ("turnover" in question) and roles.quantity and roles.inventory_on_hand:
        params["quantity_column"] = roles.quantity
        params["inventory_on_hand_column"] = roles.inventory_on_hand
        return "inventory_turnover", params, None, order

    if ("repeat" in question or "repeat purchase" in question) and roles.customer_id and roles.order_id:
        params["customer_id_column"] = roles.customer_id
        params["order_id_column"] = roles.order_id
        return "repeat_purchase_rate", params, None, order

    if ("unit price" in question) and roles.unit_price:
        params["unit_price_column"] = roles.unit_price
        return "average_unit_price", params, None, order

    if ("discount" in question) and roles.discount:
        params["discount_column"] = roles.discount
        return "effective_discount_pct", params, None, order

    ranking_words = ("which", "top", "bottom", "highest", "lowest", "best", "worst", "rank")
    if (
        allow_revenue
        and ("revenue" in question or "total sales" in question or "sales" in question)
        and roles.money
    ):
        if any(word in question for word in ranking_words):
            # A ranking question is better served by rank_categories, which can
            # also return the share of the total.
            return None, {}, None, order
        params["revenue_column"] = roles.money
        return "revenue", params, None, order

    if (
        "sold" in question
        and roles.quantity
        and ("unit" in question or "quantity" in question or "item" in question)
    ):
        params["quantity_column"] = roles.quantity
        return "units_sold", params, None, order

    return None, {}, None, order


def _period_window(period: str, bucket: str) -> tuple[str, str]:
    """Return the inclusive start/end dates of a period label."""
    import calendar

    if bucket == "month":
        year, month = (int(p) for p in period.split("-"))
        start = f"{year:04d}-{month:02d}-01"
        end = f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
        return start, end
    if bucket == "quarter":
        year, quarter = (int(p) for p in period.split("-Q"))
        start_month = 3 * (quarter - 1) + 1
        end_month = start_month + 2
        start = f"{year:04d}-{start_month:02d}-01"
        end = f"{year:04d}-{end_month:02d}-{calendar.monthrange(year, end_month)[1]:02d}"
        return start, end
    if bucket == "year":
        return f"{period}-01-01", f"{period}-12-31"
    return period, period


class FreeProvider(BaseProvider):
    """Deterministic analyst that needs no API credentials."""

    name = "free"

    def __init__(self, **options: Any) -> None:
        super().__init__(**options)
        self.info = ProviderInfo(
            name="free",
            label="Free guided mode (no API key)",
            requires_key=False,
            default_base_url="",
            default_model="deterministic-rule-engine",
            supports_native_tools=False,
            supports_model_listing=False,
            notes="Rule-based intent mapping with a visual query builder. Fully offline.",
        )

    # -- API ---------------------------------------------------------------
    async def plan(self, context: ProviderContext) -> ProviderResult:
        question = context.question.strip()
        lowered = question.lower()
        intents = [name for name, keywords in INTENT_KEYWORDS.items() if any(k in lowered for k in keywords)]
        specific_intents = [name for name in intents if name != "profile"]
        if not intents:
            intents = ["profile"]

        dataset = context.datasets[0]
        roles = _role_columns(dataset)
        steps: list[dict[str, Any]] = []
        clarification: str | None = None

        if "join" in intents and len(context.datasets) >= 2:
            steps.append(
                {
                    "tool": "join_approved_datasets",
                    "input": {
                        "left_dataset_id": context.datasets[0].id,
                        "right_dataset_id": context.datasets[1].id,
                        "left_key": "REQUIRES_USER_APPROVAL",
                        "right_key": "REQUIRES_USER_APPROVAL",
                    },
                    "reason": "The question asks to combine two datasets; the join key must be approved by the user.",
                }
            )
            clarification = (
                "Which columns should be used to join these two datasets? "
                "Approve the join key in the workspace and ask again."
            )
            return ProviderResult(
                plan={"steps": steps, "clarification": clarification},
                usage={
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "model": "deterministic",
                },
                mode="plan",
                notes=["join requires an approved key"],
            )

        if "time_series" in intents and roles.date and roles.money:
            bucket = _bucket_for(lowered)
            steps.append(
                {
                    "tool": "time_series",
                    "input": {
                        "dataset_id": dataset.id,
                        "date_column": roles.date,
                        "bucket": bucket,
                        "metrics": [{"column": roles.money, "agg": "sum", "alias": "revenue"}],
                        "include_growth": True,
                    },
                    "reason": f"Bucket revenue by {bucket} and compute period-over-period growth.",
                }
            )
            steps.append(
                {
                    "tool": "generate_chart",
                    "input": {
                        "dataset_id": dataset.id,
                        "chart_type": "line",
                        "title": f"{bucket.title()} revenue trend",
                        "x": roles.date,
                        "y": [roles.money],
                        "bucket": bucket,
                        "aggregation": "sum",
                    },
                    "reason": "Visualise the trend that was computed.",
                }
            )

        # --- KPI branch -------------------------------------------------
        kpi_name, kpi_params, kpi_group, kpi_order = _select_kpi(
            lowered, roles, allow_revenue="time_series" not in intents
        )
        if kpi_name:
            kpi_input: dict[str, Any] = {
                "dataset_id": dataset.id,
                "kpi": kpi_name,
                "params": kpi_params,
                "order": kpi_order,
            }
            if kpi_group:
                kpi_input["group_by"] = kpi_group
            steps.append(
                {
                    "tool": "compute_kpi",
                    "input": kpi_input,
                    "reason": f"Compute the {kpi_name.replace('_', ' ')} KPI with explicit column mappings.",
                }
            )
            steps.append(
                {
                    "tool": "explain_calculation",
                    "input": {
                        "dataset_id": dataset.id,
                        "calculation": kpi_name,
                        "params": kpi_params,
                    },
                    "reason": "Provide the formula and the assumptions behind the KPI.",
                }
            )

        # --- ranking branch ----------------------------------------------
        if "ranking" in intents and roles.money and not kpi_name:
            category = roles.product or roles.category or roles.region or roles.supplier or roles.customer_id
            if category:
                steps.append(
                    {
                        "tool": "rank_categories",
                        "input": {
                            "dataset_id": dataset.id,
                            "category_column": category,
                            "metric_column": roles.money,
                            "agg": "sum",
                            "top_n": 10,
                            "order": "asc" if "lowest" in lowered else "desc",
                        },
                        "reason": f"Rank {category} by total {roles.money}.",
                    }
                )
                steps.append(
                    {
                        "tool": "generate_chart",
                        "input": {
                            "dataset_id": dataset.id,
                            "chart_type": "bar",
                            "title": f"Top {category} by {roles.money}",
                            "x": category,
                            "y": [roles.money],
                            "aggregation": "sum",
                        },
                        "reason": "Show the ranking as a bar chart.",
                    }
                )
            else:
                clarification = "Which column should be ranked? The dataset has no obvious category column."

        if "period_comparison" in intents and roles.date and roles.money:
            bucket = "quarter" if "quarter" in lowered else "month"
            latest = dataset.latest_periods.get(roles.date)
            if latest:
                period = _quarter_of(latest) if bucket == "quarter" else latest
                previous = _previous_quarter(period) if bucket == "quarter" else _previous_month(period)
                if period and previous:
                    start1, end1 = _period_window(previous, bucket)
                    start2, end2 = _period_window(period, bucket)
                    group_by = [roles.region] if roles.region and "region" in lowered else None
                    steps.append(
                        {
                            "tool": "compare_periods",
                            "input": {
                                "dataset_id": dataset.id,
                                "date_column": roles.date,
                                "metric_column": roles.money,
                                "agg": "sum",
                                "period1_start": start1,
                                "period1_end": end1,
                                "period2_start": start2,
                                "period2_end": end2,
                                **({"group_by": group_by} if group_by else {}),
                            },
                            "reason": f"Compare {previous} with {period} for {roles.money}.",
                        }
                    )

        if "correlation" in intents:
            numeric = [
                str(c.get("name"))
                for c in dataset.columns
                if c.get("type") in {"numeric", "currency", "mixed_numeric"}
            ][:5]
            if len(numeric) >= 2:
                steps.append(
                    {
                        "tool": "compute_correlations",
                        "input": {
                            "dataset_id": dataset.id,
                            "columns": numeric,
                            "method": "pearson",
                        },
                        "reason": "Measure how the numeric columns move together.",
                    }
                )

        if "outliers" in intents:
            target = roles.money or (dataset.columns[0]["name"] if dataset.columns else None)
            if target:
                steps.append(
                    {
                        "tool": "detect_outliers",
                        "input": {
                            "dataset_id": dataset.id,
                            "column": target,
                            "method": "iqr",
                            "threshold": 1.5,
                        },
                        "reason": "Flag statistically unusual values.",
                    }
                )

        if "quality" in intents:
            steps.append(
                {
                    "tool": "check_data_quality",
                    "input": {"dataset_id": dataset.id},
                    "reason": "Report missing values, duplicates and type issues.",
                }
            )

        if "distribution" in intents:
            target = roles.money or (dataset.columns[0]["name"] if dataset.columns else None)
            if target:
                steps.append(
                    {
                        "tool": "compute_distribution",
                        "input": {"dataset_id": dataset.id, "column": target, "bins": 12},
                        "reason": "Summarise how the values are distributed.",
                    }
                )

        if "profile" in intents and not steps:
            steps.append(
                {
                    "tool": "profile_data",
                    "input": {"dataset_id": dataset.id},
                    "reason": "Describe the dataset with descriptive statistics.",
                }
            )
            if not specific_intents:
                clarification = (
                    "I could not map this question onto a specific analysis, so the dataset profile is shown. "
                    "Try asking for revenue, a ranking, a trend over time, a KPI, or data quality."
                )

        if "preview" in intents and not steps:
            steps.append(
                {
                    "tool": "preview_rows",
                    "input": {"dataset_id": dataset.id, "limit": 20},
                    "reason": "Show a bounded sample of the rows.",
                }
            )

        if "export" in intents:
            steps.append(
                {
                    "tool": "export_results",
                    "input": {"dataset_id": dataset.id, "format": "csv", "limit": 1000},
                    "reason": "Export the data with formula-injection sanitisation.",
                }
            )

        if "explain" in intents and not steps:
            steps.append(
                {
                    "tool": "explain_calculation",
                    "input": {"dataset_id": dataset.id, "calculation": question[:200]},
                    "reason": "Explain how the requested calculation is defined.",
                }
            )

        if not steps:
            steps.append(
                {
                    "tool": "profile_data",
                    "input": {"dataset_id": dataset.id},
                    "reason": "No specific analysis was recognised, so describe the dataset instead.",
                }
            )
            clarification = (
                "I could not map this question onto a specific analysis. "
                "The dataset profile is shown below - try asking for revenue, a ranking, a trend, or data quality."
            )

        return ProviderResult(
            plan={"steps": steps[:6], "clarification": clarification},
            usage={
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "model": "deterministic",
            },
            mode="plan",
            notes=[f"intent={','.join(intents)}", f"roles={roles.as_dict()}"],
        )

    async def narrate(self, context: ProviderContext, observations: list[dict[str, Any]]) -> str:
        """The deterministic narrative is produced by the agent, not the model."""
        raise ProviderError("the free provider does not generate narratives")

    async def list_models(self) -> list[str]:
        return ["deterministic-rule-engine"]

    async def test_connection(self) -> dict[str, Any]:
        return {"ok": True, "provider": "free", "model": "deterministic-rule-engine", "requires_key": False}
