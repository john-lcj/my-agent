"""Skill draft generation for repeated task patterns."""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any


def _draft_path(log_dir: str) -> str:
    return os.path.join(log_dir, "skill_drafts.json")


def _drafts_dir(log_dir: str) -> str:
    return os.path.join(log_dir, "skill_drafts")


def normalize_description(text: str) -> str:
    """Normalize skill descriptions to short English text."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        t = "Reusable workflow distilled from repeated tasks"
    return t[:96]


def list_drafts(log_dir: str) -> list[dict]:
    path = _draft_path(log_dir)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_drafts(log_dir: str, drafts: list[dict]) -> None:
    os.makedirs(log_dir, exist_ok=True)
    with open(_draft_path(log_dir), "w", encoding="utf-8") as f:
        json.dump(drafts[:20], f, ensure_ascii=False, indent=2)


def save_draft(log_dir: str, name: str, description: str, trigger: str, body: str) -> dict:
    drafts = list_drafts(log_dir)
    desc = normalize_description(description)
    item = {
        "id": f"draft_{int(time.time())}",
        "name": name,
        "description": desc,
        "trigger": trigger,
        "body": body,
        "status": "pending",
        "created_at": time.time(),
    }
    drafts.insert(0, item)
    os.makedirs(_drafts_dir(log_dir), exist_ok=True)
    md_path = os.path.join(_drafts_dir(log_dir), f"{item['id']}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(body)
    _write_drafts(log_dir, drafts)
    return item


def _default_draft_body(rep: str) -> str:
    return (
        f"---\nname: auto_{re.sub(r'[^a-z0-9_]', '_', rep.lower())[:20]}\n"
        f"description: {normalize_description('Reusable workflow distilled from repeated tasks')}\n"
        f"trigger: {rep[:20]}\n"
        f"risk: READ\n"
        f"---\n\n# {rep}\n\n"
        f"## Steps\n1. Understand the task goal\n2. Follow the proven historical workflow\n3. Verify the result before reporting\n"
    )


async def draft_body_with_llm(rep: str, llm=None) -> str:
    """Generate a skill draft with the LLM, falling back to a template on failure."""
    prompt = (
        f"The task pattern \"{rep}\" has repeated at least 3 times. Write a SKILL.md draft "
        "with YAML frontmatter: name/description/trigger/risk. The description must be English. "
        "The body should contain reusable steps and no extra explanation.\n\nOutput the full SKILL.md:"
    )
    if llm is None:
        return _default_draft_body(rep)
    try:
        step = await llm.next_step(
            [{"role": "user", "content": prompt}],
            [],
        )
        text = (step.text or "").strip()
        if text.startswith("---") and "description:" in text:
            return text
    except Exception:
        pass
    return _default_draft_body(rep)


def maybe_draft_from_pattern(log_dir: str, pattern: dict[str, Any], min_count: int = 3,
                             llm=None) -> dict | None:
    count = int(pattern.get("count") or 0)
    if count < min_count:
        return None
    rep = (pattern.get("rep") or pattern.get("last") or "repeated task")[:40]
    existing = list_drafts(log_dir)
    if any(rep[:12] in d.get("name", "") for d in existing):
        return None
    body = _default_draft_body(rep)
    item = save_draft(
        log_dir,
        name=f"auto_{rep[:20]}",
        description="Reusable workflow distilled from repeated tasks",
        trigger=rep[:28],
        body=body,
    )
    try:
        from core.briefing import enqueue_monitor_digest
        enqueue_monitor_digest(
            log_dir, "skill draft", "pattern",
            f"New skill draft pending confirmation:{item['name']}({rep[:30]})",
        )
    except Exception:
        pass
    return item


async def maybe_draft_from_pattern_async(log_dir: str, pattern: dict[str, Any],
                                         min_count: int = 3, llm=None) -> dict | None:
    """Async variant that can use an LLM to generate the draft."""
    count = int(pattern.get("count") or 0)
    if count < min_count:
        return None
    rep = (pattern.get("rep") or pattern.get("last") or "repeated task")[:40]
    existing = list_drafts(log_dir)
    if any(rep[:12] in d.get("name", "") for d in existing):
        return None
    body = await draft_body_with_llm(rep, llm)
    item = save_draft(
        log_dir,
        name=f"auto_{rep[:20]}",
        description="Reusable workflow distilled from repeated tasks",
        trigger=rep[:28],
        body=body,
    )
    try:
        from core.briefing import enqueue_monitor_digest
        enqueue_monitor_digest(
            log_dir, "skill draft", "pattern",
            f"New skill draft pending confirmation:{item['name']}({rep[:30]})",
        )
    except Exception:
        pass
    return item


def confirm_draft(log_dir: str, draft_id: str, skills_root: str | None = None) -> dict:
    drafts = list_drafts(log_dir)
    item = next((d for d in drafts if d.get("id") == draft_id), None)
    if item is None:
        raise KeyError(draft_id)
    if item.get("status") == "confirmed":
        return item
    root = skills_root or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills",
    )
    raw_name = re.sub(r"[^a-z0-9_]", "_", (item.get("name") or "auto_skill").lower())
    skill_dir = os.path.join(root, raw_name)
    os.makedirs(skill_dir, exist_ok=True)
    body = item.get("body") or ""
    if not body.strip().startswith("---"):
        body = (
            f"---\nname: {raw_name}\n"
            f"description: {item.get('description') or normalize_description('Reusable repeated task skill')}\n"
            f"trigger: {item.get('trigger') or raw_name}\n"
            f"risk: READ\n"
            f"---\n\n{body}\n"
        )
    with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(body)
    item["status"] = "confirmed"
    item["skill_path"] = skill_dir
    _write_drafts(log_dir, drafts)
    try:
        from memory.pattern_tracker import PatternTracker
        PatternTracker(path=os.path.join(log_dir, "task_patterns.json")).mark_crystallized(
            item.get("trigger") or item.get("name") or "",
        )
    except Exception:
        pass
    return item


def dismiss_draft(log_dir: str, draft_id: str) -> bool:
    drafts = list_drafts(log_dir)
    kept = [d for d in drafts if d.get("id") != draft_id]
    if len(kept) == len(drafts):
        return False
    _write_drafts(log_dir, kept)
    return True
