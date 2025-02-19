"""Security helpers.

The threat model for this application is:

* Spreadsheet content (cell values, file names, column names) is **untrusted
  data** and must never be interpreted as instructions.
* The language model may only select tools from the allowlist and may only
  provide structured arguments.  It can never submit code, SQL, shell
  commands, file paths or expressions.
* Exports must not be able to execute formulas in the spreadsheet application
  that opens them (CSV / XLSX formula injection).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# Prompt-injection heuristics
# --------------------------------------------------------------------------- #

#: Patterns that indicate an attempt to override the system instructions.
INJECTION_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", "instruction_override"),
    (r"disregard\s+(all\s+)?(previous|prior|above)", "instruction_override"),
    (r"you\s+are\s+now\s+", "role_reassignment"),
    (r"system\s+prompt", "system_prompt_probe"),
    (r"reveal\s+(your|the)\s+(prompt|instructions)", "system_prompt_probe"),
    (r"<\s*/?\s*(system|assistant|user)\s*>", "chat_role_tag"),
    (r"\[\s*(system|inst|instructions)\s*\]", "chat_role_tag"),
    (r"developer\s+mode", "mode_switch"),
    (r"jailbreak", "jailbreak"),
    (r"do\s+not\s+follow", "instruction_override"),
    (r"instead\s+of\s+using\s+tools", "tool_subversion"),
    (r"(run|execute)\s+(this\s+)?(python|bash|shell|code|script)", "code_execution_request"),
    (r"\b(rm\s+-rf|curl\s+.*\|\s*(ba)?sh)\b", "shell_payload"),
    (r"(drop|truncate)\s+table", "sql_payload"),
    (r"\bunion\s+select\b", "sql_payload"),
    (r"(select|insert|update|delete)\s+.*\s+from\s+", "sql_payload"),
    (r"\b(eval|exec|compile|__import__)\s*\(", "code_execution_request"),
    (r"os\.system|subprocess\.|importlib", "code_execution_request"),
    (r"(https?://)?[^\s]*(exfil|webhook|requestbin|pipedream)\S*", "data_exfiltration"),
    (r"api[_-]?key\s*[:=]\s*\S+", "credential_probe"),
)

_COMPILED_INJECTION = tuple((re.compile(p, re.IGNORECASE), label) for p, label in INJECTION_PATTERNS)

#: Strings that must never be accepted as an identifier (column, table, ...).
_FORBIDDEN_IDENTIFIER = re.compile(r"[\x00-\x1f;`'\"\\]|--|/\*|\*/")

#: Dotted-path / traversal markers.
_TRAVERSAL = re.compile(r"(^|[\\/])\.\.([\\/]|$)|^[a-zA-Z]:[\\/]|^~[\\/]")

#: Formula-injection triggers for spreadsheet exports.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def scan_text_for_injection(text: str) -> list[str]:
    """Return the labels of every injection pattern found in ``text``."""
    if not text:
        return []
    hits: list[str] = []
    for pattern, label in _COMPILED_INJECTION:
        if pattern.search(text):
            hits.append(label)
    return sorted(set(hits))


def looks_like_formula(value: Any) -> bool:
    """True when a cell value would be interpreted as a formula by Excel/Sheets."""
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if not stripped:
        return False
    return stripped[0] in _FORMULA_PREFIXES


def sanitize_export_cell(value: Any) -> Any:
    """Neutralise spreadsheet formula injection while preserving the text.

    A leading apostrophe is the conventional escape: Excel/Sheets/LibreOffice
    treat the cell as literal text.  The value is otherwise unchanged so the
    exported data stays faithful.
    """
    if isinstance(value, str) and looks_like_formula(value):
        return "'" + value
    return value


def sanitize_dataframe(df):  # pragma: no cover - thin pandas wrapper
    """Apply :func:`sanitize_export_cell` to every cell of a DataFrame."""
    if hasattr(df, "map"):  # pandas >= 2.1
        return df.map(sanitize_export_cell)
    return df.applymap(sanitize_export_cell)  # pragma: no cover


def is_safe_identifier(name: str) -> bool:
    """True when ``name`` is safe to use as a column/table identifier."""
    if not isinstance(name, str) or not name or len(name) > 200:
        return False
    if _FORBIDDEN_IDENTIFIER.search(name):
        return False
    return not _TRAVERSAL.search(name)


def sanitize_filename(filename: str | None) -> str:
    """Return a filesystem-safe basename for an uploaded file."""
    raw = (filename or "").replace("\\", "/")
    base = raw.split("/")[-1]
    base = unicodedata.normalize("NFKC", base)
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    base = base.lstrip(".") or "upload"
    if len(base) > 180:
        stem, dot, ext = base.rpartition(".")
        base = (stem[:150] + (dot + ext if dot else "")) or "upload"
    return base


def resolve_within(base_dir: Path, candidate: Path) -> Path:
    """Resolve ``candidate`` and assert it stays inside ``base_dir``."""
    base = base_dir.resolve()
    target = candidate if candidate.is_absolute() else base / candidate
    target = target.resolve()
    if base != target and base not in target.parents:
        raise ValueError("Resolved path escapes the permitted base directory")
    return target


def contains_any(text: str, needles: Iterable[str]) -> bool:
    lowered = (text or "").lower()
    return any(n.lower() in lowered for n in needles)
