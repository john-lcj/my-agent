"""personal_search skill:在个人文档索引(kind=personal_doc)中语义检索。"""
from core.types import CapabilityResult

SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Description of the content to retrieve"},
        "k": {"type": "integer", "description": "Number of snippets to return; defaults to 5"},
    },
    "required": ["query"],
}

_KIND = "personal_doc"


async def run(args: dict, ctx) -> CapabilityResult:
    query = str(args.get("query", "")).strip()
    if not query:
        return CapabilityResult(ok=False, error="缺少参数 query")
    k = int(args.get("k") or 5)

    memory = getattr(ctx, "longterm", None)
    if memory is None:
        return CapabilityResult(ok=False, error="长期记忆未挂载,无法检索个人文档")

    # retrieve 不分 kind,放大候选量后按 kind 过滤
    try:
        hits = memory.retrieve(query, k=max(k * 4, 12))
    except Exception as e:
        return CapabilityResult(ok=False, error=f"检索失败:{e}")

    docs = [h for h in hits if h.kind == _KIND][:k]
    if not docs:
        return CapabilityResult(
            ok=True,
            output="个人文档索引中没有相关内容。可能未配置 AGENT_PERSONAL_DIRS,"
                   "或定时任务「个人数据索引」还没跑过。",
        )
    blocks = [f"{i+1}. {d.content[:500]}" for i, d in enumerate(docs)]
    return CapabilityResult(ok=True, output="\n\n".join(blocks))
