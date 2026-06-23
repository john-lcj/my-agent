"""评测打分 —— 纯确定性判据,把"一次运行的产出"对照用例期望判通过与否。

expect 支持(全满足才算过):
  contains:        [子串]   每个都要出现
  any:             [子串]   至少一个出现
  not_contains:    [子串]   都不能出现
  regex:           [正则]   每个都要匹配
  not_regex:       [正则]   都不能匹配(如"用英文回答"→不该出现中文)
  max_length:      int      产出至多多少字符(防超长/不守字数约束)
  capabilities:    [能力名] 这些能力都要被调用过
  not_capabilities:[能力名] 这些能力**不能**被调用(如纯聊天不该 shell.run)
  min_length:      int      产出至少多少字符(防空/太短)
  files_exist:     [文件名] 这些文件要真落在工作区(产物/ 或工作区根),防"声称交付但没产物"

语义/开放式质量(LLM 质检员)不在这里,见 evals/judge.py(异步)。
"""
from __future__ import annotations

import os
import re


def _file_present(name: str) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    ws = os.environ.get("AGENT_WORKSPACE_ROOT", "").strip() or os.getcwd()
    cands = [
        name if os.path.isabs(name) else os.path.join(ws, name),
        os.path.join(ws, "产物", os.path.basename(name)),
        os.path.join(ws, os.path.basename(name)),
    ]
    return any(os.path.exists(p) for p in cands)


def score_case(output: str, caps_called: list[str], expect: dict,
               files_text: str = "") -> tuple[bool, list[str]]:
    """output=对话回复;files_text=本轮产出文件的拼接内容(Cowork 交付物在文件里)。"""
    out = output or ""
    caps = set(caps_called or [])
    fails: list[str] = []

    # 文件内容判据:Cowork 交付物落在文件,这里对照文件内容而非对话回复
    for s in expect.get("file_contains", []) or []:
        if s not in (files_text or ""):
            fails.append(f"产出文件里缺少:{s!r}")

    for s in expect.get("contains", []) or []:
        if s not in out:
            fails.append(f"缺少应含内容:{s!r}")
    any_list = expect.get("any", []) or []
    if any_list and not any(s in out for s in any_list):
        fails.append(f"未命中任一:{any_list}")
    for s in expect.get("not_contains", []) or []:
        if s in out:
            fails.append(f"不应出现却出现:{s!r}")
    for pat in expect.get("regex", []) or []:
        if not re.search(pat, out):
            fails.append(f"未匹配正则:{pat!r}")
    for pat in expect.get("not_regex", []) or []:
        if re.search(pat, out):
            fails.append(f"不该匹配的正则却匹配了:{pat!r}")
    max_len = expect.get("max_length")
    if isinstance(max_len, int) and len(out.strip()) > max_len:
        fails.append(f"产出超长:{len(out.strip())} > {max_len} 字符")
    for cap in expect.get("capabilities", []) or []:
        if cap not in caps:
            fails.append(f"未调用应调用的能力:{cap}")
    caps_any = expect.get("capabilities_any", []) or []
    if caps_any and not any(c in caps for c in caps_any):
        fails.append(f"这几个能力一个都没调:{caps_any}")
    for cap in expect.get("not_capabilities", []) or []:
        if cap in caps:
            fails.append(f"调用了不该调的能力:{cap}")
    ml = expect.get("min_length")
    if isinstance(ml, int) and len(out.strip()) < ml:
        fails.append(f"产出太短:{len(out.strip())} < {ml} 字符")
    for fn in expect.get("files_exist", []) or []:
        if not _file_present(fn):
            fails.append(f"应产出的文件不存在:{fn}")

    return (len(fails) == 0), fails


def summarize(results: list[dict]) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    by_cat: dict[str, dict] = {}
    for r in results:
        cat = r.get("category", "未分类")
        c = by_cat.setdefault(cat, {"total": 0, "passed": 0})
        c["total"] += 1
        c["passed"] += 1 if r.get("passed") else 0
    for c in by_cat.values():
        c["pass_rate"] = round(c["passed"] / c["total"], 3) if c["total"] else 0.0
    return {"total": total, "passed": passed, "failed": total - passed,
            "pass_rate": round(passed / total, 3) if total else 0.0,
            "by_category": by_cat}


def compare_baseline(current: list[dict], baseline: list[dict]) -> dict:
    """对比基线:找出"原来过、现在挂"的退步项(回归)和"原来挂、现在过"的修复项。"""
    base = {r.get("name"): bool(r.get("passed")) for r in (baseline or [])}
    regressed, fixed, new = [], [], []
    for r in current:
        name = r.get("name")
        now = bool(r.get("passed"))
        if name not in base:
            new.append(name)
        elif base[name] and not now:
            regressed.append(name)
        elif not base[name] and now:
            fixed.append(name)
    return {"regressed": regressed, "fixed": fixed, "new": new}
