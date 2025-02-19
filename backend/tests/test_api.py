"""HTTP API tests."""

from __future__ import annotations

import json

import pandas as pd


class TestSystem:
    def test_health(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_info_lists_tools_and_providers(self, client):
        response = client.get("/api/info")
        assert response.status_code == 200
        body = response.json()
        assert body["tool_count"] == 19
        assert "compute_kpi" in body["tools"]
        assert {p["name"] for p in body["providers"]} >= {
            "free",
            "openai",
            "anthropic",
            "openrouter",
            "custom",
            "ollama",
        }
        assert body["security"]["arbitrary_code_execution"] is False
        assert body["security"]["model_supplied_sql"] is False

    def test_request_id_header(self, client):
        response = client.get("/api/health")
        assert response.headers.get("X-Request-ID")

    def test_unknown_api_path_returns_json_404(self, client):
        response = client.get("/api/does-not-exist")
        assert response.status_code == 404
        assert "error" in response.json()


class TestDatasets:
    def test_list_datasets(self, client, demo_datasets):
        response = client.get("/api/datasets")
        assert response.status_code == 200
        names = {d["name"] for d in response.json()}
        assert "Retail Orders" in names

    def test_get_dataset(self, client, orders):
        response = client.get(f"/api/datasets/{orders.id}")
        assert response.status_code == 200
        assert response.json()["row_count"] == 5018
        assert response.json()["file_hash"] == orders.source_hash

    def test_schema_endpoint(self, client, orders):
        response = client.get(f"/api/datasets/{orders.id}/schema")
        assert response.status_code == 200
        body = response.json()
        assert body["column_count"] == 14
        assert any(c["name"] == "Revenue" for c in body["columns"])

    def test_preview_endpoint(self, client, orders):
        response = client.get(f"/api/datasets/{orders.id}/preview?limit=5")
        assert response.status_code == 200
        body = response.json()
        assert len(body["rows"]) == 5
        assert body["total_rows"] == 5018

    def test_preview_rejects_unknown_column(self, client, orders):
        response = client.get(f"/api/datasets/{orders.id}/preview?columns=Ghost")
        assert response.status_code == 400

    def test_quality_endpoint(self, client, orders):
        response = client.get(f"/api/datasets/{orders.id}/quality")
        assert response.status_code == 200
        assert 0 <= response.json()["score"] <= 100

    def test_upload_csv(self, client):
        payload = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]}).to_csv(index=False).encode()
        response = client.post(
            "/api/datasets/upload",
            files={"file": ("tiny.csv", payload, "text/csv")},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["row_count"] == 3
        assert body["column_count"] == 2

    def test_upload_rejects_unsupported_type(self, client):
        response = client.post(
            "/api/datasets/upload",
            files={"file": ("evil.exe", b"MZ\x00\x00", "application/octet-stream")},
        )
        assert response.status_code == 400

    def test_upload_rejects_oversized_file(self, client, monkeypatch):
        from app.core import config

        monkeypatch.setattr(config.settings, "max_upload_size_mb", 0)
        payload = b"a,b\n1,2\n"
        response = client.post("/api/datasets/upload", files={"file": ("x.csv", payload, "text/csv")})
        assert response.status_code == 413

    def test_delete_dataset(self, client, db, demo_files):
        from app.ingest import store

        raw = (store.settings.demo_dir / "customers.csv").read_bytes()
        stored = store.create_dataset(db, raw=raw, filename="customers.csv")
        response = client.delete(f"/api/datasets/{stored.dataset.id}")
        assert response.status_code == 200
        assert client.get(f"/api/datasets/{stored.dataset.id}").status_code == 404

    def test_export_csv(self, client, orders):
        response = client.get(f"/api/datasets/{orders.id}/export?format=csv")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert "Order_ID" in response.text


class TestAnalysisApi:
    def test_query(self, client, orders):
        response = client.post(
            "/api/analysis/query",
            json={
                "question": "What were monthly sales and growth rates?",
                "dataset_ids": [orders.id],
                "provider": "free",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "completed"
        assert body["tool_trace"]
        assert body["evidence"]["datasets"]
        assert body["how_calculated"]["steps"]

    def test_query_rejects_unknown_fields(self, client, orders):
        response = client.post(
            "/api/analysis/query",
            json={
                "question": "What is the revenue?",
                "dataset_ids": [orders.id],
                "provider": "free",
                "execute_code": True,
            },
        )
        assert response.status_code == 422

    def test_query_rejects_short_question(self, client, orders):
        response = client.post(
            "/api/analysis/query",
            json={"question": "x", "dataset_ids": [orders.id]},
        )
        assert response.status_code == 422

    def test_query_rejects_unknown_dataset(self, client):
        response = client.post(
            "/api/analysis/query",
            json={"question": "What is the revenue?", "dataset_ids": ["missing-id"]},
        )
        assert response.status_code == 422

    def test_history_and_detail(self, client, orders):
        client.post(
            "/api/analysis/query",
            json={"question": "What was total revenue?", "dataset_ids": [orders.id], "provider": "free"},
        )
        history = client.get("/api/analysis/history")
        assert history.status_code == 200
        assert history.json()
        analysis_id = history.json()[0]["id"]
        detail = client.get(f"/api/analysis/history/{analysis_id}")
        assert detail.status_code == 200
        assert detail.json()["tool_trace"]

    def test_conversations(self, client, orders):
        client.post(
            "/api/analysis/query",
            json={"question": "What was total revenue?", "dataset_ids": [orders.id], "provider": "free"},
        )
        response = client.get("/api/analysis/conversations")
        assert response.status_code == 200
        assert response.json()[0]["message_count"] == 2

    def test_tool_catalogue(self, client):
        response = client.get("/api/analysis/tools")
        assert response.status_code == 200
        assert len(response.json()) == 19

    def test_direct_tool_execution_requires_authorisation(self, client, orders):
        response = client.post(
            "/api/analysis/tools/execute",
            json={"tool": "inspect_schema", "arguments": {"dataset_id": orders.id}, "dataset_ids": []},
        )
        # No authorised dataset -> the dispatcher must refuse.
        assert response.status_code == 403


class TestSettingsApi:
    def test_providers_are_listed_without_secrets(self, client):
        response = client.get("/api/settings/providers")
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 6
        for provider in body:
            assert "api_key" not in provider
            assert provider["masked_key"] is None or "*" in provider["masked_key"]

    def test_config_exposes_limits_and_kpis(self, client):
        response = client.get("/api/settings/config")
        assert response.status_code == 200
        body = response.json()
        assert body["max_tool_rounds"] >= 1
        assert any(kpi["name"] == "revenue" for kpi in body["kpi_catalogue"])

    def test_provider_can_be_saved_and_is_masked(self, client):
        response = client.post(
            "/api/settings/providers",
            json={
                "provider": "custom",
                "base_url": "http://localhost:1234/v1",
                "api_key": "sk-super-secret-value",
                "model": "my-model",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert "sk-super-secret-value" not in json.dumps(body)
        assert body["masked_key"] != "sk-super-secret-value"

        providers = client.get("/api/settings/providers").json()
        custom = next(p for p in providers if p["provider"] == "custom")
        assert "sk-super-secret-value" not in json.dumps(custom)
        assert custom["has_key"] is True

    def test_provider_test_without_key_is_reported(self, client):
        response = client.post("/api/settings/providers/test", json={"provider": "openai", "api_key": ""})
        assert response.status_code == 200
        assert response.json()["ok"] is False

    def test_metric_definition_can_be_created(self, client, orders):
        response = client.post(
            "/api/settings/metrics",
            json={
                "dataset_id": orders.id,
                "name": "net_revenue",
                "label": "Net revenue",
                "kpi": "revenue",
                "params": {"revenue_column": "Revenue"},
                "is_approved": True,
            },
        )
        assert response.status_code == 201
        assert response.json()["params"]["revenue_column"] == "Revenue"

    def test_join_approval(self, client, orders, demo_datasets):
        customers = demo_datasets["Customers"]
        response = client.post(
            "/api/settings/joins",
            json={
                "left_dataset_id": orders.id,
                "right_dataset_id": customers.id,
                "left_key": "Customer_ID",
                "right_key": "Customer_ID",
            },
        )
        assert response.status_code == 201
        assert client.get("/api/settings/joins").json()


class TestReports:
    def test_report_lifecycle(self, client, orders):
        client.post(
            "/api/analysis/query",
            json={"question": "What was total revenue?", "dataset_ids": [orders.id], "provider": "free"},
        )
        analysis_id = client.get("/api/analysis/history").json()[0]["id"]
        created = client.post(
            "/api/reports",
            json={
                "title": "Revenue snapshot",
                "analysis_id": analysis_id,
                "chart": {"chart_type": "bar", "title": "Revenue", "data": [{"x": "A", "Revenue": 1}]},
            },
        )
        assert created.status_code == 201
        report_id = created.json()["id"]

        pdf = client.get(f"/api/reports/{report_id}/export?format=pdf")
        assert pdf.status_code == 200
        assert pdf.content[:4] == b"%PDF"

        csv = client.get(f"/api/reports/{report_id}/export?format=csv")
        assert csv.status_code == 200
        assert "Revenue" in csv.text

        assert client.delete(f"/api/reports/{report_id}").status_code == 200


class TestVisualBuilder:
    def test_run_tool_endpoint(self, client, orders):
        response = client.post(
            "/api/tools/run",
            json={
                "tool": "aggregate_metrics",
                "arguments": {
                    "dataset_id": orders.id,
                    "metrics": [{"column": "Revenue", "agg": "sum", "alias": "revenue"}],
                },
                "dataset_ids": [orders.id],
            },
        )
        assert response.status_code == 200
        assert response.json()["data"]["results"][0]["revenue"] > 0

    def test_run_tool_rejects_unknown_tool(self, client, orders):
        response = client.post(
            "/api/tools/run",
            json={"tool": "run_python", "arguments": {}, "dataset_ids": [orders.id]},
        )
        assert response.status_code == 403
