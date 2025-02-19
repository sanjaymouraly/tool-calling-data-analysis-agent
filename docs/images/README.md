# Screenshots

Every image in this folder is a **real screenshot of the running application**,
captured with Playwright against the production build. Nothing here is a mock-up.

## Regenerating them

```bash
# 1. Build the frontend
cd frontend && npm install && npm run build

# 2. Start the API (it serves the compiled bundle on port 8000)
cd ../backend && uvicorn app.main:app --port 8000

# 3. Capture
cd .. && node scripts/capture_screenshots.mjs http://localhost:8000 docs/images
```

The script fails with a non-zero exit code if the browser logs any console error,
so a screenshot is never produced from a broken page.

| File | What it shows |
|---|---|
| `dashboard.png` | The overview: dataset statistics, ready-to-run questions, recent analyses. |
| `datasets.png` | The dataset manager with the imported files and their hashes. |
| `schema.png` | The inferred schema: types, semantic roles, missing values, samples. |
| `data-quality.png` | The data-quality report: score, missing values, outliers, warnings. |
| `preview.png` | A bounded preview of the rows. |
| `workspace.png` | The conversational workspace with the answer and the tool trace. |
| `workspace-answer.png` | The evidence-backed answer in detail. |
| `charts.png` | A chart rendered from a validated chart specification. |
| `evidence.png` | The "How this was calculated" panel: source hash, formulas, assumptions. |
| `tool-trace.png` | The tool execution trace with the arguments of every call. |
| `builder.png` | The visual query builder (the API-free path). |
| `history.png` | The persisted analysis history. |
| `settings.png` | The provider wizard and the security model. |
| `dashboard-dark.png` | The dark theme. |
