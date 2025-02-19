#!/usr/bin/env python3
"""Evaluation CLI.

Examples::

    python backend/evaluate.py                       # deterministic (free) path
    python backend/evaluate.py --provider openai     # a hosted provider
    python backend/evaluate.py --json report.json --markdown report.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.evaluation.runner import run_evaluation, write_report  # noqa: E402

PREAMBLE = """# Evaluation report

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
"""


def render_markdown(report) -> str:
    lines = [
        PREAMBLE,
        "## Result",
        "",
        f"- Provider: `{report.provider}`",
        f"- Started: {report.started_at}",
        f"- Duration: {report.duration_ms} ms",
        f"- Result: **{report.passed}/{report.total} passed** ({report.pass_rate}%)",
        f"- Dataset hash: `{report.dataset_hash}`",
        "",
        "| Fixture | Question | Status | Tools | Latency |",
        "|---|---|---|---|---|",
    ]
    for result in report.results:
        lines.append(
            f"| `{result.id}` | {result.question} | **{result.status}** | "
            f"{', '.join(result.tools_used) or '-'} | {result.latency_ms} ms |"
        )
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    for note in report.notes:
        lines.append(f"- {note}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the analysis benchmark")
    parser.add_argument("--provider", default="free", help="provider to benchmark (default: free)")
    parser.add_argument("--json", dest="json_path", default="evaluation_report.json")
    parser.add_argument("--markdown", dest="markdown_path", default=None)
    parser.add_argument("--strict", action="store_true", help="exit non-zero when a fixture fails")
    args = parser.parse_args()

    report = run_evaluation(args.provider)

    print(f"\n=== Evaluation ({args.provider}) ===")
    for result in report.results:
        marker = "PASS" if result.status == "pass" else "FAIL"
        print(f"  [{marker}] {result.id:<24} {result.latency_ms:>6} ms  {', '.join(result.tools_used)}")
        for check in result.values:
            if not check["ok"]:
                print(
                    f"         value mismatch: {check['metric']} expected {check['expected']} "
                    f"got {check['actual']}"
                )
        if result.error and result.status != "pass":
            print(f"         {result.error}")
    print(
        f"\nTotal: {report.total}, Passed: {report.passed}, Failed: {report.failed}, "
        f"Pass rate: {report.pass_rate}%"
    )

    write_report(report, Path(args.json_path))
    print(f"JSON report written to {args.json_path}")
    if args.markdown_path:
        Path(args.markdown_path).write_text(render_markdown(report))
        print(f"Markdown report written to {args.markdown_path}")

    if args.strict and report.failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
