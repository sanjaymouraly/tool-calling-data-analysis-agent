"""Tests for the agent workflow, plan validation and evidence generation."""

from __future__ import annotations

import asyncio

import pytest

from app.agent.narrative import build_how_calculated, build_narrative
from app.agent.verify import extract_claims, verify_claims
from app.agent.workflow import AnalysisRequest, run_analysis
from app.db.models import AnalysisRecord, Conversation
from app.tools.base import registry


def ask(db, question: str, dataset_ids: list[str], provider: str = "free", **kwargs):
    return asyncio.run(
        run_analysis(
            db,
            AnalysisRequest(question=question, dataset_ids=dataset_ids, provider=provider, **kwargs),
        )
    )


class TestFreeWorkflow:
    def test_monthly_sales(self, db, orders):
        outcome = ask(db, "What were monthly sales and growth rates?", [orders.id])
        assert outcome.status == "completed"
        assert [s["tool"] for s in outcome.tool_trace] == ["time_series", "generate_chart"]
        assert outcome.charts
        assert "### Evidence" in outcome.answer
        assert "sha256" in outcome.answer

    def test_top_products(self, db, orders):
        outcome = ask(db, "Which products generated the highest revenue?", [orders.id])
        assert outcome.status == "completed"
        assert "rank_categories" in [s["tool"] for s in outcome.tool_trace]

    def test_aov(self, db, orders):
        outcome = ask(db, "What is the average order value, and how was it calculated?", [orders.id])
        assert outcome.status == "completed"
        assert "Average order value" in outcome.answer
        assert "COUNT(DISTINCT" in outcome.answer

    def test_data_quality(self, db, orders):
        outcome = ask(db, "Where are missing values, duplicated records, or unusual changes?", [orders.id])
        assert outcome.status == "completed"
        assert "Data-quality score" in outcome.answer

    def test_period_comparison(self, db, orders):
        outcome = ask(db, "Compare regional performance this quarter versus last quarter.", [orders.id])
        assert outcome.status == "completed"
        assert "Period 1" in outcome.answer and "Period 2" in outcome.answer

    def test_unrecognised_question_asks_for_clarification(self, db, orders):
        outcome = ask(db, "What is the meaning of life for this business?", [orders.id])
        assert outcome.status == "needs_clarification"
        assert outcome.clarification
        assert "Clarification needed" in outcome.answer

    def test_unknown_dataset_is_rejected(self, db):
        from app.core.errors import ValidationError

        with pytest.raises(ValidationError):
            ask(db, "What is the revenue?", ["00000000-0000-0000-0000-000000000000"])


class TestEvidence:
    def test_evidence_contains_hash_and_rows(self, db, orders):
        outcome = ask(db, "What was total revenue?", [orders.id])
        datasets = outcome.evidence["datasets"]
        assert len(datasets) == 1
        assert datasets[0]["file_hash"] == orders.source_hash
        assert datasets[0]["row_count"] == orders.row_count
        assert datasets[0]["version"] == orders.version

    def test_every_tool_call_has_evidence(self, db, orders):
        outcome = ask(db, "What was total revenue?", [orders.id])
        for entry in outcome.evidence["tool_evidence"]:
            assert entry["tool"] in registry.names()
            assert entry["evidence"]

    def test_how_calculated_has_formulas(self, db, orders):
        outcome = ask(db, "What is the average order value?", [orders.id])
        how = outcome.how_calculated
        assert how["steps"]
        assert how["assumptions"]
        assert how["definitions"]["percentage_change"]
        assert how["execution_metadata"]["tool_count"] >= 1

    def test_narrative_only_contains_allowlisted_tools(self, db, orders):
        outcome = ask(db, "What were monthly sales and growth rates?", [orders.id])
        for step in outcome.tool_trace:
            assert step["tool"] in registry.names()


class TestPersistence:
    def test_analysis_is_stored(self, db, orders):
        outcome = ask(db, "What was total revenue?", [orders.id])
        record = db.get(AnalysisRecord, outcome.record.id)
        assert record is not None
        assert record.question == "What was total revenue?"
        assert record.tool_trace_json
        assert record.evidence_json
        assert record.provider == "free"

    def test_conversation_messages_are_stored(self, db, orders):
        outcome = ask(db, "What was total revenue?", [orders.id])
        conversation = db.get(Conversation, outcome.conversation_id)
        assert conversation is not None
        roles = [m.role for m in conversation.messages]
        assert roles == ["user", "assistant"]

    def test_history_survives_a_new_session(self, db, orders):
        ask(db, "What was total revenue?", [orders.id])
        db.expire_all()
        records = db.query(AnalysisRecord).all()
        assert len(records) >= 1

    def test_conversation_can_be_continued(self, db, orders):
        first = ask(db, "What was total revenue?", [orders.id])
        second = ask(
            db,
            "Which products generated the highest revenue?",
            [orders.id],
            conversation_id=first.conversation_id,
        )
        assert second.conversation_id == first.conversation_id
        conversation = db.get(Conversation, first.conversation_id)
        assert len(conversation.messages) == 4


class TestProviderFallback:
    def test_falls_back_to_free_when_the_provider_fails(self, db, orders, monkeypatch):
        from app.providers import openai_compat

        async def boom(self, context):
            raise openai_compat.ProviderError("provider unreachable")

        monkeypatch.setattr(openai_compat.OpenAICompatProvider, "plan", boom)
        outcome = ask(db, "What was total revenue?", [orders.id], provider="openai")
        assert outcome.status == "completed"
        assert outcome.provider == "free"
        assert any("could not produce a plan" in note for note in outcome.evidence.get("notes", []))

    def test_invalid_plan_falls_back_to_free(self, db, orders, monkeypatch):
        from app.providers import openai_compat

        async def bad_plan(self, context):
            return openai_compat.ProviderResult(plan={"steps": [{"tool": "rm_rf", "input": {}}]})

        monkeypatch.setattr(openai_compat.OpenAICompatProvider, "plan", bad_plan)
        outcome = ask(db, "What was total revenue?", [orders.id], provider="openai")
        assert outcome.status == "completed"
        assert outcome.provider == "free"
        for step in outcome.tool_trace:
            assert step["tool"] in registry.names()


class TestVerification:
    def test_claims_are_extracted(self):
        claims = extract_claims("Revenue was $1,234.56 which is 12.5% higher")
        assert any(c["value"] == 1234.56 for c in claims)
        assert any(c["percent"] for c in claims)

    def test_grounded_claims_are_verified(self):
        observations = [{"data": {"revenue": 1234.56}}]
        result = verify_claims("The revenue was 1,234.56", observations)
        assert result["all_verified"]

    def test_invented_claims_are_flagged(self):
        observations = [{"data": {"revenue": 1234.56}}]
        result = verify_claims("The revenue was 9,999,999", observations)
        assert not result["all_verified"]
        assert result["unverified_claims"]

    def test_zero_is_not_a_claim(self):
        assert extract_claims("there were 0 issues") == []


class TestNarrative:
    def test_narrative_lists_evidence(self):
        trace = [
            {
                "step": 1,
                "tool": "compute_kpi",
                "status": "success",
                "output": {
                    "data": {
                        "kpi": "revenue",
                        "label": "Total revenue",
                        "value": 100.0,
                        "unit": "currency",
                        "currency": "USD",
                        "column_resolution": {"money": {"column": "Revenue", "resolution": "explicit"}},
                    }
                },
            }
        ]
        datasets = [
            {
                "id": "abc",
                "name": "Demo",
                "version": 1,
                "row_count": 10,
                "column_count": 2,
                "file_hash": "deadbeef",
            }
        ]
        text = build_narrative("What is the revenue?", trace, datasets)
        assert "Total revenue" in text
        assert "$100.00" in text
        assert "### Evidence" in text

    def test_failed_tool_is_reported(self):
        trace = [{"step": 1, "tool": "compute_kpi", "status": "error", "error": "boom"}]
        text = build_narrative("What is the revenue?", trace, [])
        assert "Caveats" in text
        assert "boom" in text

    def test_how_calculated_structure(self):
        trace = [
            {
                "step": 1,
                "tool": "compute_kpi",
                "status": "success",
                "input": {"dataset_id": "x"},
                "output": {"data": {"formula": "SUM(Revenue)"}, "_meta": {"elapsed_ms": 12}},
            }
        ]
        how = build_how_calculated(trace, [], {"steps": []}, provider="free", model=None)
        assert how["steps"][0]["formula"] == "SUM(Revenue)"
        assert how["steps"][0]["elapsed_ms"] == 12
