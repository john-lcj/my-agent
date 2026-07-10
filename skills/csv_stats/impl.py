"""csv_stats skill:读取 CSV 给出概览统计(行列/类型/数值统计/缺失)。"""
from __future__ import annotations

import csv
import io
import os
import statistics

from core.types import CapabilityResult
from governance.workspace import resolve_path

SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "CSV file path; use either path or csv_text"},
        "csv_text": {"type": "string", "description": "Inline CSV text"},
        "delimiter": {"type": "string", "description": "Delimiter; defaults to comma"},
    },
}


def _num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


async def run(args: dict, ctx) -> CapabilityResult:
    path = str(args.get("path", "")).strip()
    text = args.get("csv_text")
    delim = (str(args.get("delimiter") or ",") or ",")[0]

    if path:
        path, error = resolve_path(path, require_exists=True)
        if error or not os.path.isfile(path):
            return CapabilityResult(ok=False, error=f"文件不存在:{path}")
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                content = f.read()
        except Exception as e:
            return CapabilityResult(ok=False, error=f"读取失败:{e}")
    elif text is not None:
        content = str(text)
    else:
        return CapabilityResult(ok=False, error="需提供 path 或 csv_text")

    rows = [r for r in csv.reader(io.StringIO(content), delimiter=delim)
            if any(str(c).strip() for c in r)]
    if not rows:
        return CapabilityResult(ok=True, output="(空表)")

    header, data = rows[0], rows[1:]
    out = [f"行数(不含表头)={len(data)},列数={len(header)}", "列概览:"]
    for i, col in enumerate(header):
        vals = [r[i] if i < len(r) else "" for r in data]
        missing = sum(1 for v in vals if not str(v).strip())
        present = len(vals) - missing
        nums = [x for x in (_num(v) for v in vals) if x is not None]
        # 八成以上有效值能转数值 -> 视为数值列
        if nums and present and len(nums) >= present * 0.8:
            line = (f"  [{col}] 数值列:n={len(nums)} 缺失={missing} "
                    f"min={min(nums):.4g} max={max(nums):.4g} "
                    f"均值={statistics.mean(nums):.4g} "
                    f"中位={statistics.median(nums):.4g}")
        else:
            uniq = len({str(v).strip() for v in vals if str(v).strip()})
            sample = next((str(v).strip() for v in vals if str(v).strip()), "")
            line = f"  [{col}] 文本列:唯一值={uniq} 缺失={missing} 示例={sample[:30]}"
        out.append(line)
    return CapabilityResult(ok=True, output="\n".join(out))
