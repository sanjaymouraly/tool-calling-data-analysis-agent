# API reference

Base URL: `http://localhost:8000`. Interactive documentation: `/api/docs`
(OpenAPI schema at `/api/openapi.json`).

All responses are JSON. Errors use a stable envelope:

```json
{ "error": { "code": "validation_error", "message": "…", "details": {} } }
```

---

## System

### `GET /api/health`
Liveness probe.

```json
{ "status": "ok", "app": "Tool-Calling Data Analysis Agent", "version": "1.0.0", "environment": "local" }
```

### `GET /api/info`
Capabilities: the tool catalogue, the supported providers, the KPI list, the configured
limits and the security posture.

### `GET /api/audit`
The audit trail (uploads, deletions, provider changes, analyses).

---

## Datasets

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/datasets` | List datasets. Query: `include_demo`, `search`, `limit`. |
| `GET` | `/api/datasets/{id}` | Full dataset record including the schema and quality profile. |
| `POST` | `/api/datasets/upload` | Import a file (multipart). Fields: `file`, `sheet_name`, `description`. |
| `GET` | `/api/datasets/{id}/schema` | Inferred column types, roles, missing counts, samples. |
| `GET` | `/api/datasets/{id}/preview` | Bounded page of rows. Query: `limit`, `offset`, `columns`. |
| `GET` | `/api/datasets/{id}/quality` | Missing values, duplicates, outliers, type issues, score. |
| `GET` | `/api/datasets/{id}/columns` | Column search. Query: `q`. |
| `GET` | `/api/datasets/{id}/sheets` | Sheet names of a workbook. |
| `GET` | `/api/datasets/{id}/export` | Download. Query: `format=csv\|xlsx\|json`, `limit`. |
| `POST` | `/api/datasets/{id}/approve` | Mark a dataset as approved. Query: `approved`. |
| `DELETE` | `/api/datasets/{id}` | Delete the dataset, its artefact and the stored file. |
| `POST` | `/api/datasets/demo/seed` | Re-seed the synthetic demo datasets. |

```bash
curl -F file=@data/demo/retail_orders.csv http://localhost:8000/api/datasets/upload
```

---

## Analysis

### `POST /api/analysis/query`

```json
{
  "question": "What were monthly sales and growth rates?",
  "dataset_ids": ["<uuid>"],
  "provider": "free",
  "conversation_id": null,
  "approved_joins": [
    { "left_dataset_id": "<uuid>", "right_dataset_id": "<uuid>",
      "left_key": "Customer_ID", "right_key": "Customer_ID" }
  ],
  "max_rounds": 8
}
```

Response:

```json
{
  "id": "<analysis-id>",
  "conversation_id": "<uuid>",
  "question": "…",
  "answer": "### Result\n**…**\n\n### Evidence\n…",
  "status": "completed",
  "plan": { "steps": [ { "tool": "time_series", "input": {…}, "reason": "…" } ] },
  "tool_trace": [ { "step": 1, "tool": "time_series", "status": "success",
                    "input": {…}, "output": {…}, "evidence": {…} } ],
  "evidence": { "datasets": [ { "id": "…", "file_hash": "…", "row_count": 5018 } ],
                "tool_evidence": [ … ], "verifiable": true, "note": "…" },
  "how_calculated": { "steps": [ … ], "definitions": {…}, "assumptions": [ … ] },
  "charts": [ { "chart_type": "line", "title": "…", "data": [ … ] } ],
  "usage": { "prompt_tokens": 0, "completion_tokens": 0, "estimated_cost_usd": 0.0 },
  "verification": { "all_verified": true, "unverified_claims": [] },
  "clarification": null,
  "provider": "free",
  "model": "deterministic-rule-engine",
  "latency_ms": 42,
  "states": ["inspect", "plan", "validate", "execute", "verify", "answer", "persist"]
}
```

`status` is one of `completed`, `needs_clarification` or `failed`.

### Other analysis endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/analysis/history` | Persisted analyses. Query: `search`, `dataset_id`, `limit`, `offset`. |
| `GET` | `/api/analysis/history/{id}` | The full record including the tool trace. |
| `GET` | `/api/analysis/conversations` | Conversations. |
| `GET` | `/api/analysis/conversations/{id}` | A conversation with its messages. |
| `DELETE` | `/api/analysis/conversations/{id}` | Delete a conversation. |
| `GET` | `/api/analysis/tools` | The complete tool catalogue with JSON schemas. |
| `GET` | `/api/analysis/tools/catalogue` | A compact catalogue. |
| `POST` | `/api/analysis/tools/execute` | Run one allowlisted tool directly. |

```bash
curl -X POST http://localhost:8000/api/analysis/tools/execute \
  -H 'Content-Type: application/json' \
  -d '{"tool":"compute_kpi",
       "arguments":{"dataset_id":"<uuid>","kpi":"revenue",
                    "params":{"revenue_column":"Revenue"}},
       "dataset_ids":["<uuid>"]}'
```

---

## Visual query builder

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/tools/catalog` | The tool catalogue. |
| `GET` | `/api/tools/kpis` | The KPI catalogue with formulas and required roles. |
| `POST` | `/api/tools/run` | Run one tool: `{tool, arguments, dataset_ids}`. |

---

## Settings

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/settings/config` | Limits, defaults and the KPI catalogue. |
| `GET` | `/api/settings/providers` | Provider status (never a raw key). |
| `POST` | `/api/settings/providers` | Save a provider configuration. |
| `POST` | `/api/settings/providers/test` | Test a connection. |
| `DELETE` | `/api/settings/providers/{provider}` | Remove a stored configuration. |
| `GET` | `/api/settings/providers/{provider}/models` | List the models a provider offers. |
| `GET` | `/api/settings/usage` | Token and cost accounting. |
| `GET`/`POST` | `/api/settings/metrics` | Approved metric definitions. |
| `GET`/`POST` | `/api/settings/joins` | Approved join relationships. |
| `GET`/`POST` | `/api/settings/calendars` | Business calendars. |

---

## Reports

| Method | Path | Description |
|---|---|---|
| `GET`/`POST` | `/api/reports` | List or create a saved report. |
| `DELETE` | `/api/reports/{id}` | Delete a report. |
| `GET` | `/api/reports/{id}/export` | Export as `pdf`, `csv` or `json`. |
