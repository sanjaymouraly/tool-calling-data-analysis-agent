# Evaluation report

The benchmark checks that the *system* answers correctly: the right tools are
selected, the numbers match an independently computed reference, and the answer
cites its evidence.

**The reference values are not produced by the application.** They are computed by
`backend/app/demo/generator.py` with plain pandas arithmetic over the source CSV -
a second, independent implementation of the same calculation. The tool trace is
stored for every fixture so the arithmetic can be re-checked by hand.

Regenerate this report with:

```bash
cd backend
python evaluate.py --json ../evaluation_report.json --markdown ../docs/EVALUATION.md
```

| Check | Meaning |
|---|---|
| `tools_match` | The plan used the expected allowlisted tools. |
| `values` | The numeric output matches the independent reference within the stated tolerance. |
| `citation_complete` | The answer contains the evidence block and the dataset hashes. |
| `expected_answer_contains` | The narrative contains the expected result fragments. |
| `latency_ms` | End-to-end duration of the workflow. |
| `estimated_cost_usd` | Token cost, zero for the deterministic path. |

## Live provider verification

The deterministic path proves the tool boundary and the arithmetic. It says
**nothing** about the accuracy of a hosted language model, and this report does not
claim otherwise.

What *was* verified live in the build environment is the provider integration
itself: the local Ollama provider (`gemma3:1b`) passed its connection test, its
model discovery and a real plan request. The 1B model returned a plan without a
`steps` array, which the validator **rejected**; the workflow fell back to the
deterministic analyst and still returned a correct, fully cited answer - the
security model working end-to-end against a live model.

The hosted adapters (OpenAI, Anthropic, OpenRouter, custom) were covered by
mocked-HTTP tests only, because no hosted credentials were available. They are
implemented but **not verified against the live services**.

Re-run the benchmark against a hosted provider with:

```bash
cd backend
OPENAI_API_KEY=... python evaluate.py --provider openai --json report-openai.json
```

## Result

- Provider: `free`
- Started: 2026-10-19T14:05:31Z
- Duration: 483 ms
- Result: **9/9 passed** (100.0%)
- Dataset hash: `16856f559dd958035371bbc2ba2bc5ba4418e3175af056b9a7e54f8a3b42b151`

| Fixture | Question | Status | Tools | Latency |
|---|---|---|---|---|
| `monthly-sales` | What were monthly sales and growth rates? | **pass** | time_series, generate_chart | 62 ms |
| `top-products` | Which products generated the highest revenue? | **pass** | rank_categories, generate_chart | 40 ms |
| `average-order-value` | What is the average order value, and how was it calculated? | **pass** | compute_kpi, explain_calculation | 44 ms |
| `total-revenue` | What was total revenue? | **pass** | compute_kpi, explain_calculation | 39 ms |
| `data-quality` | Where are missing values, duplicated records, or unusual changes? | **pass** | detect_outliers, check_data_quality | 49 ms |
| `period-comparison` | Compare regional performance this quarter versus last quarter. | **pass** | compare_periods | 40 ms |
| `supplier-on-time` | Which suppliers have the lowest on-time delivery percentage? | **pass** | compute_kpi, explain_calculation | 42 ms |
| `churn-rate` | What is the churn rate among customers? | **pass** | compute_kpi, explain_calculation | 37 ms |
| `units-sold` | How many units were sold in total? | **pass** | compute_kpi, explain_calculation | 37 ms |

## Notes

- Reference values are computed independently by the demo generator using pandas.
- The free path proves the tool boundary and the arithmetic, not the accuracy of any hosted language model.