"""A deterministic 50-case browser benchmark catalog."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BrowserBenchmarkCase:
    case_id: str
    category: str
    action: str
    expected: str
    high_impact: bool = False


_CATEGORIES = (
    ("navigation", "open", "page loaded"),
    ("form_fill", "fill", "value accepted"),
    ("form_submit", "click", "success state"),
    ("downloads", "download", "artifact hash verified"),
    ("uploads", "upload", "file accepted"),
    ("delays", "wait", "delayed element visible"),
    ("isolation", "context", "cookie boundary preserved"),
    ("takeover", "takeover", "owner resumed task", True),
    ("failures", "retry", "bounded failure recorded"),
    ("verification", "assert", "remote state verified"),
)


def benchmark_cases() -> list[BrowserBenchmarkCase]:
    cases: list[BrowserBenchmarkCase] = []
    for category, action, expected, *impact in _CATEGORIES:
        for index in range(5):
            cases.append(BrowserBenchmarkCase(
                case_id=f"browser-{category}-{index + 1}", category=category,
                action=action, expected=expected, high_impact=bool(impact and impact[0]),
            ))
    return cases


def benchmark_summary(cases: list[BrowserBenchmarkCase] | None = None) -> dict[str, object]:
    cases = cases or benchmark_cases()
    return {"total": len(cases), "categories": sorted({case.category for case in cases}),
            "high_impact": sum(case.high_impact for case in cases)}
