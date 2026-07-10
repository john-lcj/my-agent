"""Reusable office workflow definitions and benchmark cases."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OfficeWorkflow:
    slug: str
    name: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    risk: str = "low"


OFFICE_WORKFLOWS = (
    OfficeWorkflow("inbox_triage", "Inbox triage", ("email_thread",), ("classification", "drafts")),
    OfficeWorkflow("weekly_report", "Weekly report", ("work_notes",), ("docx", "evidence")),
    OfficeWorkflow("meeting_minutes", "Meeting minutes", ("transcript",), ("docx", "action_items")),
    OfficeWorkflow("spreadsheet_analysis", "Spreadsheet analysis", ("xlsx",), ("xlsx", "summary")),
    OfficeWorkflow("research_report", "Research report", ("sources",), ("docx", "evidence")),
    OfficeWorkflow("slide_deck", "Slide deck", ("outline",), ("pptx", "render_check")),
    OfficeWorkflow("calendar_coordination", "Calendar coordination", ("availability",), ("event", "audit")),
)


def benchmark_cases() -> list[dict[str, str]]:
    cases = []
    for workflow in OFFICE_WORKFLOWS:
        for index in range(5):
            cases.append({"id": f"{workflow.slug}-{index + 1}", "workflow": workflow.slug,
                          "expected": workflow.outputs[index % len(workflow.outputs)]})
    return cases
