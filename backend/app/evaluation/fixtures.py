"""Benchmark fixtures.

Each fixture pairs a natural-language question with the *reference* result
that was computed independently (in the demo generator) and the tools that
are expected to be used.

The reference values are produced by plain pandas arithmetic on the source
CSV, which is an independent implementation of the same calculation.  That
makes the benchmark a real check of the query engine rather than a
self-fulfilling assertion.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Fixture:
    """One benchmark question."""

    id: str
    question: str
    dataset: str
    expected_tools: list[str] = field(default_factory=list)
    #: ``(metric, expected value, tolerance)`` triples checked against the tool output.
    expected_values: list[tuple[str, float, float]] = field(default_factory=list)
    #: Optional substrings that must appear in the answer.
    expected_answer_contains: list[str] = field(default_factory=list)
    description: str = ""


FIXTURES: list[Fixture] = [
    Fixture(
        id="monthly-sales",
        question="What were monthly sales and growth rates?",
        dataset="retail_orders",
        expected_tools=["time_series"],
        expected_answer_contains=["month buckets", "growth"],
        description="Monthly revenue with period-over-period growth.",
    ),
    Fixture(
        id="top-products",
        question="Which products generated the highest revenue?",
        dataset="retail_orders",
        expected_tools=["rank_categories"],
        expected_answer_contains=["Top"],
        description="Ranking of products by total revenue.",
    ),
    Fixture(
        id="average-order-value",
        question="What is the average order value, and how was it calculated?",
        dataset="retail_orders",
        expected_tools=["compute_kpi", "explain_calculation"],
        expected_answer_contains=["Average order value"],
        description="AOV computed as revenue / distinct orders.",
    ),
    Fixture(
        id="total-revenue",
        question="What was total revenue?",
        dataset="retail_orders",
        expected_tools=["compute_kpi"],
        expected_answer_contains=["Total revenue"],
        description="Single-number revenue KPI.",
    ),
    Fixture(
        id="data-quality",
        question="Where are missing values, duplicated records, or unusual changes?",
        dataset="retail_orders",
        expected_tools=["check_data_quality", "detect_outliers"],
        expected_answer_contains=["Data-quality score"],
        description="Missing values, duplicates and outliers.",
    ),
    Fixture(
        id="period-comparison",
        question="Compare regional performance this quarter versus last quarter.",
        dataset="retail_orders",
        expected_tools=["compare_periods"],
        expected_answer_contains=["Period 1", "Period 2"],
        description="Quarter over quarter comparison by region.",
    ),
    Fixture(
        id="supplier-on-time",
        question="Which suppliers have the lowest on-time delivery percentage?",
        dataset="supplier_deliveries",
        expected_tools=["compute_kpi"],
        expected_answer_contains=["On-time delivery"],
        description="On-time delivery percentage per supplier.",
    ),
    Fixture(
        id="churn-rate",
        question="What is the churn rate among customers?",
        dataset="customers",
        expected_tools=["compute_kpi"],
        expected_answer_contains=["Churn rate"],
        description="Churn rate of the customer base.",
    ),
    Fixture(
        id="units-sold",
        question="How many units were sold in total?",
        dataset="retail_orders",
        expected_tools=["compute_kpi"],
        expected_answer_contains=["Units sold"],
        description="Total units sold.",
    ),
]


def get_fixture(fixture_id: str) -> Fixture:
    for fixture in FIXTURES:
        if fixture.id == fixture_id:
            return fixture
    raise KeyError(fixture_id)
