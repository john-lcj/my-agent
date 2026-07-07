"""date_calc skill:日期加减 / 星期 / 相差天数。"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from core.types import CapabilityResult

SCHEMA = {
    "type": "object",
    "properties": {
        "op": {
            "type": "string",
            "enum": ["add", "weekday", "diff", "today"],
            "description": "add days / weekday / diff between dates / today",
        },
        "date": {"type": "string", "description": "Base date YYYY-MM-DD; defaults to today"},
        "days": {"type": "integer", "description": "Days to add or subtract for add mode"},
        "to": {"type": "string", "description": "Target date YYYY-MM-DD for diff mode; defaults to today"},
    },
}

_WD = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _parse(s: str) -> date:
    return datetime.strptime(str(s).strip(), "%Y-%m-%d").date()


async def run(args: dict, ctx) -> CapabilityResult:
    op = str(args.get("op") or "today").lower()
    try:
        base = _parse(args["date"]) if args.get("date") else date.today()
    except ValueError:
        return CapabilityResult(ok=False, error="date 格式应为 YYYY-MM-DD")

    if op == "today":
        t = date.today()
        return CapabilityResult(ok=True, output=f"今天 {t.isoformat()}({_WD[t.weekday()]})")
    if op == "weekday":
        return CapabilityResult(ok=True, output=f"{base.isoformat()} 是 {_WD[base.weekday()]}")
    if op == "add":
        n = int(args.get("days") or 0)
        d = base + timedelta(days=n)
        sign = "+" if n >= 0 else ""
        return CapabilityResult(
            ok=True, output=f"{base.isoformat()} {sign}{n} 天 = {d.isoformat()}({_WD[d.weekday()]})")
    if op == "diff":
        try:
            to = _parse(args["to"]) if args.get("to") else date.today()
        except (ValueError, KeyError):
            return CapabilityResult(ok=False, error="diff 需 to=YYYY-MM-DD")
        delta = (to - base).days
        rel = "之后" if delta >= 0 else "之前"
        return CapabilityResult(
            ok=True, output=f"{base.isoformat()} → {to.isoformat()} 相差 {abs(delta)} 天({to.isoformat()} 在基准{rel})")
    return CapabilityResult(ok=False, error=f"未知 op:{op}")
