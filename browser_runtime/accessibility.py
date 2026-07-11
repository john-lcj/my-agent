"""Accessibility-first browser target discovery and strict locator selection."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AccessibleNode:
    ref: str
    role: str
    name: str
    label: str = ""
    value: str = ""
    disabled: bool = False
    checked: bool | None = None
    expanded: bool | None = None


def normalize_nodes(raw: list[dict[str, Any]]) -> list[AccessibleNode]:
    return [AccessibleNode(
        ref=str(item.get("ref", "")), role=str(item.get("role", "")),
        name=str(item.get("name", "")), label=str(item.get("label", "")),
        value=str(item.get("value", "")), disabled=bool(item.get("disabled", False)),
        checked=item.get("checked"), expanded=item.get("expanded"),
    ) for item in raw if item.get("ref")]


def select_unique(nodes: list[AccessibleNode], *, ref: str = "", role: str = "",
                  name: str = "", label: str = "", text: str = "") -> AccessibleNode:
    candidates = nodes
    if ref:
        candidates = [node for node in candidates if node.ref == ref]
    elif label:
        candidates = [node for node in candidates if node.label == label]
    elif role or name:
        candidates = [node for node in candidates if (not role or node.role == role)
                      and (not name or node.name == name)]
    elif text:
        candidates = [node for node in candidates if text in node.name]
    if len(candidates) != 1:
        raise ValueError(f"browser target must resolve to exactly one element; got {len(candidates)}")
    if candidates[0].disabled:
        raise ValueError("browser target is disabled")
    return candidates[0]
