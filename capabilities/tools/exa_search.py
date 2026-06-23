"""Exa 语义搜索 —— 比基础 web.search 更适合 agent 的"发现式"研究检索。

Exa 用 embedding 语义检索(非关键词匹配),返回更相关的网页 + 正文片段,适合调研。
需配置 EXA_API_KEY。API:POST https://api.exa.ai/search,头 x-api-key。
"""
from __future__ import annotations

import os
from typing import Any

from capabilities.tools.base import Tool
from core.types import CapabilityResult, Risk


class ExaSearch(Tool):
    name = "exa.search"
    risk = Risk.READ
    description = (
        "用 Exa 做高质量语义网络搜索(发现式、更相关,适合调研/找资料/找最新进展),"
        "返回排序后的网页标题、链接与正文摘要。需配置 EXA_API_KEY;研究类任务优先用它。")
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索查询(自然语言即可)"},
            "num_results": {"type": "integer", "description": "返回条数,默认 5,最多 10"},
            "include_text": {"type": "boolean", "description": "是否附正文摘要,默认 true"},
        },
        "required": ["query"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        key = os.environ.get("EXA_API_KEY", "").strip()
        if not key:
            return CapabilityResult(ok=False, error="未配置 EXA_API_KEY,无法使用 Exa 搜索")
        query = str(args.get("query", "")).strip()
        if not query:
            return CapabilityResult(ok=False, error="缺少 query")
        try:
            n = int(args.get("num_results", 5))
        except (TypeError, ValueError):
            n = 5
        n = max(1, min(n, 10))
        url = "https://api.exa.ai/search"
        from governance.egress import check_egress
        ok_e, why = check_egress(url)
        if not ok_e:
            return CapabilityResult(ok=False, error=why)
        body: dict = {"query": query, "numResults": n, "type": "auto"}
        if args.get("include_text", True):
            body["contents"] = {"text": {"maxCharacters": 800}}
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(url, json=body,
                                 headers={"x-api-key": key, "Content-Type": "application/json"})
        except Exception as e:
            return CapabilityResult(ok=False, error=f"Exa 请求失败:{e}")
        if r.status_code >= 400:
            return CapabilityResult(ok=False, error=f"Exa HTTP {r.status_code}:{r.text[:200]}")
        results = (r.json() or {}).get("results", [])
        if not results:
            return CapabilityResult(ok=True, output="(Exa 没有返回结果)")
        lines: list[str] = []
        for i, it in enumerate(results, 1):
            title = (it.get("title") or "(无标题)").strip()
            link = it.get("url", "")
            lines.append(f"{i}. {title}\n   {link}")
            txt = (it.get("text") or "").strip().replace("\n", " ")
            if txt:
                lines.append(f"   摘要:{txt[:300]}")
        return CapabilityResult(ok=True, output="\n".join(lines))
