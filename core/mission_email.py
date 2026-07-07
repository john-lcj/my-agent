"""邮件 ↔ Mission 恢复 —— 解析 inbound 邮件并恢复 BLOCKED mission。"""
from __future__ import annotations

import re
from typing import Optional

_MISSION_SUBJ = re.compile(
    r"\[Captain Mission #([a-f0-9]{6,12})\]", re.I)
_MISSION_ID = re.compile(
    r"mission\s*id\s*[:：]\s*([a-f0-9]{6,12})", re.I)
_SUBJECT_LINE = re.compile(r"^\[Email subject:(.+?)\]\s*$", re.M)


def extract_email_subject(text: str) -> str:
    m = _SUBJECT_LINE.search(text or "")
    return m.group(1).strip() if m else ""


def extract_email_body(text: str) -> str:
    raw = text or ""
    lines = raw.splitlines()
    if lines and lines[0].startswith("[Email subject:"):
        return "\n".join(lines[1:]).strip()
    return raw.strip()


def parse_mission_id_prefix(subject: str, body: str) -> Optional[str]:
    for src in (subject, body):
        if not src:
            continue
        m = _MISSION_SUBJ.search(src)
        if m:
            return m.group(1).lower()
        m = _MISSION_ID.search(src)
        if m:
            return m.group(1).lower()
    return None


def resolve_mission_id(store, prefix: str) -> Optional[str]:
    if not prefix or store is None:
        return None
    prefix = prefix.lower()
    for m in store.list():
        mid = str(m.get("id") or "")
        if mid.startswith(prefix):
            return mid
    return None


def try_parse_mission_resume(text: str, store) -> Optional[tuple[str, str]]:
    """若邮件是 mission 恢复信,返回 (mission_id, info_body)。"""
    subject = extract_email_subject(text)
    body = extract_email_body(text)
    prefix = parse_mission_id_prefix(subject, body)
    if not prefix:
        return None
    mid = resolve_mission_id(store, prefix)
    if not mid:
        return None
    info = body[:2000].strip()
    if not info:
        info = "(邮件补充)"
    return mid, info
