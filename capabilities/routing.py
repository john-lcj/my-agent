"""能力路由 —— 按任务文本选出相关能力子集，减少每步发给 LLM 的 token 数。

原理：
- ALWAYS_INCLUDE：无论何种任务都包含（核心能力，约 13 个）
- ROUTING_TABLE ：前缀 → 触发关键词，命中即激活该前缀下全部能力
- skill.*       ：用户自定义，始终全量包含（不应因路由而隐藏）

效果：多数对话从 ~45 个 specs 降到 ~15-20 个，节省约 40-60% 的 capability 部分 token。
"""
from __future__ import annotations

# ── 始终包含（精确名称匹配）────────────────────────────────────────────────────
ALWAYS_INCLUDE: frozenset[str] = frozenset({
    "plan.update",
    "memory.remember", "memory.recall",
    "fs.read", "fs.list", "fs.write", "fs.search",
    "web.search", "web.fetch", "http.request", "exa.search",
    "shell.run",
    "skill.scaffold",
})

# ── 前缀路由表：(前缀, 触发关键词) ────────────────────────────────────────────
# 命中任意关键词，则把以该前缀开头的所有能力加入本次 specs。
ROUTING_TABLE: list[tuple[str, list[str]]] = [
    ("browser.", [
        "浏览器", "登录", "填表", "browser", "login", "click", "form",
        "网站", "website", "网页操作", "打开网页",
    ]),
    ("image.", [
        "图片", "图像", "生成图", "画图", "image", "photo", "picture",
        "draw", "cogview", "runware", "文生图", "ocr", "文字识别", "扫描",
    ]),
    ("vision.", [
        "截图", "识别图", "vision", "看图", "视觉", "ocr", "文字识别", "扫描",
    ]),
    ("calendar.", [
        "日历", "日程", "calendar", "ical", "事件", "约会", "会议安排",
    ]),
    ("schedule.", [
        "定时", "schedule", "定期", "每天", "每周", "每月", "cron", "自动执行",
    ]),
    ("git.", [
        "git", "提交", "commit", "仓库", "版本", "diff", "push", "pull", "代码版本",
    ]),
    ("monitor.", [
        "监控", "monitor", "监听", "告警", "alert", "watch", "盯着",
    ]),
    ("goal.", [
        "目标", "goal", "target", "设目标", "设定目标",
    ]),
    ("notify.", [
        "邮件", "发邮件", "notify", "email", "通知发送", "发送通知",
    ]),
    ("wechat.", [
        "微信", "公众号", "wechat", "推文", "公号文章", "微信文章",
    ]),
    ("secret.", [
        "密码", "密钥", "secret", "password", "凭据", "登录信息", "存密码",
    ]),
    ("program.", [
        "程序记忆", "program memory", "代码模板", "记代码",
    ]),
    ("gui.", [
        "gui", "桌面", "界面控制", "鼠标点击",
    ]),
    ("suggest.", [
        "建议", "suggest", "推荐功能", "功能建议",
    ]),
    ("skill.", [
        "技能", "skill", "工作流", "外贸", "写作技能",
    ]),
]


def route(user_text: str, all_specs: list[dict]) -> list[dict]:
    """从 all_specs 里按任务文本选出相关能力子集。

    Args:
        user_text: 用户这轮的原始输入文本。
        all_specs: registry.specs() 的全量列表。

    Returns:
        过滤后的 specs 子集，保证 ALWAYS_INCLUDE 和命中前缀全部在内。
        skill.* 始终全量包含。
    """
    text_lower = (user_text or "").lower()

    # 计算激活的前缀集合
    active_prefixes: set[str] = set()
    for prefix, keywords in ROUTING_TABLE:
        if any(kw in text_lower for kw in keywords):
            active_prefixes.add(prefix)

    result: list[dict] = []
    for spec in all_specs:
        name: str = spec.get("name", "")
        # 1. 精确命中 ALWAYS_INCLUDE
        if name in ALWAYS_INCLUDE:
            result.append(spec)
            continue
        # 2. skill.* 始终包含（用户自定义，不过滤）
        if name.startswith("skill."):
            result.append(spec)
            continue
        # 3. 前缀命中激活组
        if any(name.startswith(p) for p in active_prefixes):
            result.append(spec)

    return result
