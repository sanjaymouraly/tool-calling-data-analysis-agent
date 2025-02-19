# Contributing

Thanks for taking the time to improve the project. This document explains how to get
set up, what the project expects from a change, and how the quality gates work.

## Getting set up

```bash
git clone <your-fork> tool-using-data-analyst.git
cd tool-using-data-analyst

python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements-dev.txt

cd frontend && npm install && cd ..
```

Windows PowerShell:

```powershell
py -3.12 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r backend\requirements-dev.txt
cd frontend; npm install; cd ..
```

## Running everything locally

```bash
# API on :8000
cd backend && uvicorn app.main:app --reload

# Frontend on :5173
cd frontend && npm run dev
```

## The quality gates

| Gate | Command |
|---|---|
| Backend tests | `cd backend && pytest -q` |
| Backend lint | `cd backend && ruff check app tests evaluate.py && ruff format --check app tests evaluate.py` |
| Backend types | `cd backend && mypy app --ignore-missing-imports` |
| Backend security scan | `cd backend && bandit -r app -ll` |
| Frontend unit tests | `cd frontend && npm run test` |
| Frontend types | `cd frontend && npm run typecheck` |
| Frontend build | `cd frontend && npm run build` |
| End-to-end | `npx playwright test` (build the frontend first) |
| Benchmark | `cd backend && python evaluate.py --strict` |

CI runs all of them on every push and pull request.

## Design rules

These are not style preferences - they are the properties that make the application
trustworthy. A change that breaks one of them will be rejected.

1. **The model never executes anything.** A tool call is a name plus a JSON object.
   The registry is closed; the argument models use `extra="forbid"`.
2. **No model-supplied SQL.** Values are bound; identifiers are allow-listed against
   the dataset's own columns.
3. **A request only reads the datasets it was authorised for.** Check the identifiers
   in `ToolContext.authorized_dataset_ids`.
4. **Spreadsheet content is data.** Never treat a cell, a column name or a file name as
   an instruction - and never pass one into a prompt as if it were one.
5. **Numbers are computed, not narrated.** If a figure appears in an answer it must
   come from a tool output. The verification step enforces this.
6. **Never silently infer a business KPI.** If a KPI's columns cannot be resolved,
   fail with `missing_column_mapping` and list the roles that are missing.
7. **Document the trade-off.** A new dependency, a new limit or a changed default
   belongs in the README and the changelog.

## Adding a tool

1. Add the input model to `app/domain/tool_specs.py` (strict, bounded, `extra="forbid"`).
2. Implement the handler in `app/tools/catalog.py` and register it with
   `@register_tool(...)`.
3. Build the SQL from a template in `app/engine/duck.py`; never concatenate a value.
4. Return an `evidence` block with the dataset id, the hash, the row counts and the
   filters that were applied.
5. Add tests: the happy path, an invalid-argument path and a security path.
6. Update the tool table in the README and the catalogue endpoint.

## Adding a provider

1. Implement `BaseProvider` in `app/providers/`.
2. Return the same `ProviderResult` shape as the other adapters.
3. Never send raw dataset rows - only the schema context.
4. Add a mocked-HTTP test for the success path, the error path and the timeout path.

## Commit and pull request conventions

* One logical change per pull request.
* Write a descriptive commit subject (`fix: keep the chart buckets chronological`).
* Update `CHANGELOG.md` under *Unreleased*.
* If you change the UI, re-capture the screenshots:
  `node scripts/capture_screenshots.mjs http://localhost:8000 docs/images`.

## Reporting bugs

Open an issue with the question, the dataset (a synthetic one is fine), the expected
result and the actual result. If the answer was wrong, the tool trace from the
analysis record is the most useful thing you can attach.
