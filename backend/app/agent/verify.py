"""Numeric claim verification.

The narrative written by a language model is *checked* against the tool
outputs before it is shown to the user.  Every number that appears in the
narrative must either

* appear verbatim in the serialised observations, or
* match a value inside the observations within a small relative tolerance.

Numbers that cannot be verified are reported back to the caller so the UI can
flag them.  The verification never modifies the narrative - it annotates it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

NUMBER_RE = re.compile(
    r"(?<![\w.])"
    r"(?P<currency>[$€£¥])?"
    r"(?P<number>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d+)"
    r"\s*(?P<percent>%|percent|pct)?",
    re.IGNORECASE,
)

DEFAULT_TOLERANCE = 0.005


def collect_numbers(payload: Any) -> list[float]:
    """Collect every numeric value inside a nested structure."""
    values: list[float] = []
    stack: list[Any] = [payload]
    while stack:
        current = stack.pop()
        if isinstance(current, bool):
            continue
        if isinstance(current, (int, float)):
            values.append(float(current))
        elif isinstance(current, dict):
            stack.extend(current.values())
        elif isinstance(current, (list, tuple, set)):
            stack.extend(current)
        elif isinstance(current, str):
            for match in NUMBER_RE.finditer(current):
                try:
                    values.append(float(match.group("number").replace(",", "")))
                except ValueError:
                    continue
    return values


def extract_claims(text: str) -> list[dict[str, Any]]:
    """Extract the numeric claims made by a narrative."""
    claims: list[dict[str, Any]] = []
    for match in NUMBER_RE.finditer(text or ""):
        raw = match.group("number")
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        if value == 0 and not match.group("percent"):
            # 0 is almost always filler; keep it only if percent-marked.
            continue
        claims.append(
            {
                "text": match.group(0).strip(),
                "value": value,
                "percent": bool(match.group("percent")),
                "start": match.start(),
            }
        )
    return claims


def verify_claims(
    narrative: str,
    observations: Iterable[Any],
    *,
    tolerance: float = DEFAULT_TOLERANCE,
) -> dict[str, Any]:
    """Verify the numeric claims of a narrative against the observations."""
    observation_list = list(observations)
    serialized = json.dumps(observation_list, default=str)
    observed_values = collect_numbers(observation_list)

    verified: list[dict[str, Any]] = []
    unverified: list[dict[str, Any]] = []

    for claim in extract_claims(narrative):
        raw_text = claim["text"]
        bare = raw_text.replace(",", "").replace("$", "").replace("€", "").replace("£", "").replace("¥", "")
        bare = bare.replace("%", "").strip()
        if bare and bare in serialized:
            verified.append({**claim, "match": "verbatim"})
            continue
        if _matches_observed(claim["value"], observed_values, tolerance):
            verified.append({**claim, "match": "tolerance"})
            continue
        unverified.append(claim)

    return {
        "total_claims": len(verified) + len(unverified),
        "verified_claims": verified,
        "unverified_claims": unverified,
        "all_verified": not unverified,
        "observation_count": len(observation_list),
    }


def _matches_observed(value: float, observed: list[float], tolerance: float) -> bool:
    if not observed:
        return False
    for candidate in observed:
        if candidate == value:
            return True
        scale = max(abs(candidate), abs(value), 1.0)
        if abs(candidate - value) / scale <= tolerance:
            return True
    return False


def verified_numbers(observations: Iterable[Any]) -> list[float]:
    """Convenience helper used by the tests."""
    return collect_numbers(list(observations))
