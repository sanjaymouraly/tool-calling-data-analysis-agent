"""The benchmark runner.

The runner executes every fixture against a live dataset and reports:

* whether the plan used the expected tools,
* whether the numeric results match the independently computed reference,
* whether the answer cites its evidence,
* how long the request took and what it cost (when a provider is used).

The report is written as JSON so it can be diffed between runs in CI.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..agent.workflow import AnalysisRequest, run_analysis
from ..core.config import settings
from ..core.logging import get_logger
from ..db.base import SessionLocal
from ..db.models import Dataset
from ..ingest import store
from .fixtures import FIXTURES, Fixture

log = get_logger("evaluation")


@dataclass
class FixtureResult:
    id: str
    question: str
    dataset: str
    status: str
    tools_used: list[str] = field(default_factory=list)
    expected_tools: list[str] = field(default_factory=list)
    tools_match: bool = False
    values: list[dict[str, Any]] = field(default_factory=list)
    values_match: bool = True
    citation_complete: bool = False
    latency_ms: int = 0
    provider: str = "free"
    model: str | None = None
    estimated_cost_usd: float = 0.0
    error: str | None = None


@dataclass
class EvaluationReport:
    total: int
    passed: int
    failed: int
    provider: str
    dataset_hash: str | None = None
    results: list[FixtureResult] = field(default_factory=list)
    started_at: str = ""
    duration_ms: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return round(self.passed / self.total * 100, 2) if self.total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": self.pass_rate,
            "provider": self.provider,
            "dataset_hash": self.dataset_hash,
            "started_at": self.started_at,
            "duration_ms": self.duration_ms,
            "notes": self.notes,
            "results": [asdict(result) for result in self.results],
        }


def attach_reference_values(fixtures: list[Fixture], reference: dict[str, Any]) -> list[Fixture]:
    """Fill the numeric expectations from the independently computed reference.

    The reference file is produced by the demo generator with plain pandas
    arithmetic, so comparing the tool output against it is a genuine
    cross-implementation check.
    """
    orders = reference.get("retail_orders", {})
    deliveries = reference.get("supplier_deliveries", {})
    customers = reference.get("customers", {})

    mapping: dict[str, list[tuple[str, float, float]]] = {
        "monthly-sales": [
            ("last_period_value", orders.get("last_month_revenue", 0), 0.01),
            ("last_period_growth", orders.get("last_month_growth_pct", 0), 0.01),
            ("period_count", orders.get("monthly_periods", 0), 0),
        ],
        "top-products": [
            ("top_value", orders.get("top_product_revenue", 0), 0.01),
        ],
        "average-order-value": [
            ("kpi_value", orders.get("average_order_value", 0), 0.001),
            ("detail::distinct_orders", orders.get("distinct_orders", 0), 0),
        ],
        "total-revenue": [
            ("kpi_value", orders.get("revenue_total", 0), 0.01),
        ],
        "units-sold": [
            ("kpi_value", orders.get("units_sold", 0), 0.01),
        ],
        "supplier-on-time": [
            # The KPI is computed per supplier, so the expectation is the
            # worst supplier's percentage rather than the dataset total.
            (
                f"group::{deliveries.get('worst_supplier', '')}",
                deliveries.get("worst_supplier_on_time_pct", 0),
                0.01,
            ),
        ],
        "churn-rate": [
            ("kpi_value", customers.get("churn_rate", 0), 0.01),
        ],
    }
    for fixture in fixtures:
        if fixture.id in mapping:
            fixture.expected_values = mapping[fixture.id]
    return fixtures


def _load_reference() -> dict[str, Any]:
    import json

    path = settings.demo_dir / "reference_values.json"
    if not path.exists():
        from ..demo import generator

        generator.write_demo_data(settings.demo_dir)
    if path.exists():
        reference = json.loads(path.read_text())
        if "customers" not in reference:
            # The file predates the customer reference block: regenerate it.
            from ..demo import generator

            reference = generator.write_demo_data(settings.demo_dir)
        return reference
    return {}


def _ensure_datasets(db) -> dict[str, Dataset]:
    """Return the demo datasets, ingesting them if necessary."""
    mapping = {
        "retail_orders": "retail_orders.csv",
        "customers": "customers.csv",
        "inventory": "inventory.csv",
        "supplier_deliveries": "supplier_deliveries.csv",
    }
    from ..demo import seed

    seed.ensure_demo_files()
    resolved: dict[str, Dataset] = {}
    for key, filename in mapping.items():
        path = settings.demo_dir / filename
        if not path.exists():
            continue
        raw = path.read_bytes()
        import hashlib

        digest = hashlib.sha256(raw).hexdigest()
        dataset = (
            db.query(Dataset).filter(Dataset.source_hash == digest, Dataset.deleted_at.is_(None)).first()
        )
        if dataset is None:
            stored = store.create_dataset(db, raw=raw, filename=filename, is_demo=True)
            dataset = stored.dataset
        resolved[key] = dataset
    return resolved


def _extract_values(tool_trace: list[dict[str, Any]]) -> dict[str, Any]:
    """Collect the interesting numbers from a tool trace."""
    values: dict[str, Any] = {}
    for step in tool_trace:
        if step.get("status") != "success":
            continue
        data = (step.get("output") or {}).get("data", {}) or {}
        tool = step.get("tool")
        if tool == "compute_kpi":
            if data.get("value") is not None:
                values["kpi_value"] = data["value"]
            elif data.get("groups"):
                # A grouped KPI: the first group is the one the question asked for.
                first = data["groups"][0]
                values["kpi_value"] = first.get("value")
                values["group::first"] = first.get("value")
            for group in data.get("groups", []) or []:
                values[f"group::{group.get('group')}"] = group.get("value")
            for key, item in (data.get("details") or {}).items():
                if isinstance(item, (int, float)) and not isinstance(item, bool):
                    values[f"detail::{key}"] = item
        elif tool == "rank_categories":
            ranked = data.get("ranked") or []
            if ranked:
                values["top_value"] = ranked[0].get("value")
                values["top_category"] = ranked[0].get("category")
        elif tool == "time_series":
            periods = data.get("periods") or []
            if periods:
                values["last_period_value"] = periods[-1].get("revenue")
                values["last_period_growth"] = periods[-1].get("growth_pct")
                values["period_count"] = len(periods)
        elif tool == "compare_periods":
            values["period1_value"] = (data.get("period1") or {}).get("value")
            values["period2_value"] = (data.get("period2") or {}).get("value")
        elif tool == "check_data_quality":
            values["quality_score"] = data.get("score")
            values["duplicate_rows"] = (data.get("duplicates") or {}).get("count")
    return values


def _check_values(fixture: Fixture, values: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    all_ok = True
    for metric, expected, tolerance in fixture.expected_values:
        actual = values.get(metric)
        ok = actual is not None and abs(float(actual) - float(expected)) <= tolerance
        checks.append(
            {
                "metric": metric,
                "expected": expected,
                "actual": actual,
                "tolerance": tolerance,
                "ok": ok,
            }
        )
        all_ok = all_ok and ok
    return all_ok, checks


def run_evaluation(
    provider: str = "free",
    *,
    db=None,
    fixtures: list[Fixture] | None = None,
) -> EvaluationReport:
    """Run the benchmark and return the report."""
    owns_session = db is None
    session = db or SessionLocal()
    started = time.perf_counter()
    results: list[FixtureResult] = []
    dataset_hash: str | None = None
    fixtures = fixtures or FIXTURES

    try:
        datasets = _ensure_datasets(session)
        fixtures = attach_reference_values(list(fixtures), _load_reference())
        for fixture in fixtures:
            dataset = datasets.get(fixture.dataset)
            if dataset is None:
                results.append(
                    FixtureResult(
                        id=fixture.id,
                        question=fixture.question,
                        dataset=fixture.dataset,
                        status="skipped",
                        error="dataset not available",
                    )
                )
                continue
            dataset_hash = dataset_hash or dataset.source_hash
            try:
                outcome = asyncio.run(
                    run_analysis(
                        session,
                        AnalysisRequest(
                            question=fixture.question,
                            dataset_ids=[dataset.id],
                            provider=provider,
                        ),
                    )
                )
            except Exception as exc:  # pragma: no cover - defensive
                results.append(
                    FixtureResult(
                        id=fixture.id,
                        question=fixture.question,
                        dataset=fixture.dataset,
                        status="error",
                        error=str(exc)[:300],
                    )
                )
                continue

            tools_used = [step["tool"] for step in outcome.tool_trace if step.get("status") == "success"]
            tools_match = all(expected in tools_used for expected in fixture.expected_tools)
            values = _extract_values(outcome.tool_trace)
            values_match, checks = _check_values(fixture, values)
            answer = outcome.answer or ""
            citation_complete = bool(
                outcome.evidence and outcome.evidence.get("datasets") and "### Evidence" in answer
            )
            answer_ok = all(fragment in answer for fragment in fixture.expected_answer_contains)
            status = "pass" if (tools_match and values_match and citation_complete and answer_ok) else "fail"

            results.append(
                FixtureResult(
                    id=fixture.id,
                    question=fixture.question,
                    dataset=fixture.dataset,
                    status=status,
                    tools_used=tools_used,
                    expected_tools=fixture.expected_tools,
                    tools_match=tools_match,
                    values=checks,
                    values_match=values_match,
                    citation_complete=citation_complete,
                    latency_ms=outcome.latency_ms,
                    provider=outcome.provider,
                    model=outcome.model,
                    estimated_cost_usd=float((outcome.usage or {}).get("estimated_cost_usd") or 0.0),
                    error=None if status == "pass" else "one or more checks failed",
                )
            )

        passed = sum(1 for result in results if result.status == "pass")
        report = EvaluationReport(
            total=len(results),
            passed=passed,
            failed=len(results) - passed,
            provider=provider,
            dataset_hash=dataset_hash,
            results=results,
            started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            duration_ms=int((time.perf_counter() - started) * 1000),
            notes=[
                "Reference values are computed independently by the demo generator using pandas.",
                "The free path proves the tool boundary and the arithmetic, not the accuracy "
                "of any hosted language model.",
            ],
        )
        return report
    finally:
        if owns_session:
            session.close()


def write_report(report: EvaluationReport, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2))
    return path
