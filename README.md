# Tool-Calling Data Analysis Agent

An AI agent that plans and executes data-analysis tasks through controlled tool calls.

## Features

- Import: CSV, XLSX (multi-sheet) and Parquet. Files are validated, hashed (SHA-256), stored with lineage and versioned.
- Infer: Column types, currency detection, date parsing, null counts, distinct counts, descriptive statistics, semantic *role* hints (money, date, order id, supplier, …).
- Profile: Missing values, duplicate rows, IQR outliers, mixed-type columns, constant columns, a 0–100 quality score with actionable warnings.
- Analyse: 19 allowlisted tools: filtering, aggregation, grouping, time bucketing, KPI computation, period comparison, ranking, outliers, correlations, distributions, approved joins, charts, exports.
- Answer: Natural-language question → validated plan → tool execution → numeric verification → grounded narrative with an expandable *“How this was calculated”* panel.
- Prove: Every answer stores the dataset hash, the version, the row counts, the filters, the period boundaries, the formula and the full tool trace.
- Work offline: The deterministic free mode needs no API key at all and never sends data anywhere.

## Stack

Python, Node.js, FastAPI, Uvicorn, Pydantic, SQLAlchemy, pandas, NumPy, openpyxl, HTTPX

## Clone

```bash
git clone https://github.com/sanjaymouraly/tool-calling-data-analysis-agent.git
cd tool-calling-data-analysis-agent
```

## Setup

```bash
# The project ships a Docker Compose setup.
docker compose up --build
```

See `docs/` or the compose file for environment variables and ports.

## Run

```bash
docker compose up --build
```

## Tests

```bash
pytest -q
```

## Notes

- Sample data, when included, is synthetic.

## License

MIT © 2025 [Sanjay Mouraly](https://github.com/sanjaymouraly)
