"""轻量语境判断层。

目标不是替模型做深度推理,而是在每轮开始前给 Captain 一个内部姿态:
现在更像顾问、审阅者、执行者、研究员、产品经理,还是安全官。

第一阶段刻意只用本地规则,不额外调用模型,保持毫秒级和稳定可测。
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class IntentFrame:
    role: str
    task_kind: str
    confidence: float
    needs_plan: bool = False
    needs_sources: bool = False
    needs_confirmation: bool = False
    should_edit_files: bool = False
    brief: str = ""


_SECURITY_RE = re.compile(
    r"(token|api[_-]?key|secret|auth_secret|agent_api_token|agent_workspace_root|"
    r"密钥|凭据|令牌|权限|安全|暴露|远程访问|公网|删除|支付|收款|授权码|"
    r"\.env|ssh|密码)",
    re.I,
)
_REVIEW_RE = re.compile(
    r"(review|审阅|代码审查|帮我看看|看一下|检查|核对|有没有\s*bug|bug|问题|风险|哪里不对)",
    re.I,
)
_RESEARCH_RE = re.compile(
    r"(调研|研究|搜索|查一下|查找|资料|竞品|最新|最近|新闻|价格|政策|法规|引用|来源|benchmark)",
    re.I,
)
_EXECUTOR_RE = re.compile(
    r"(修复|实现|继续|完成|改成|改为|新增|删除|提交|推送|部署|上线|生成|创建|"
    r"写入|同步|安装|更新|跑测试|执行|把.+放到|把.+改)",
    re.I,
)
_PM_RE = re.compile(
    r"(建议|怎么看|你觉得|方向|路线|规划|产品|商业|定价|优先级|取舍|策略|定位|卖点|路线图)",
    re.I,
)
_ADVISOR_RE = re.compile(r"(解释|说明|为什么|怎么实现|原理|区别|是什么|如何)", re.I)


def classify_intent(user_text: str, ctx=None) -> IntentFrame:
    text = (user_text or "").strip()
    low = text.lower()

    if _SECURITY_RE.search(text):
        return IntentFrame(
            role="security",
            task_kind="risk_boundary",
            confidence=0.88,
            needs_plan=True,
            needs_confirmation=True,
            brief="涉及安全、权限、凭据、远程访问或不可逆操作。先识别风险边界,不要回显秘密,高风险动作必须确认。",
        )

    if _REVIEW_RE.search(text):
        return IntentFrame(
            role="reviewer",
            task_kind="review",
            confidence=0.80,
            needs_plan=False,
            should_edit_files=False,
            brief="这是审阅/检查任务。先读相关上下文并按严重程度给发现;默认不要改文件,除非用户明确要求修复。",
        )

    if _RESEARCH_RE.search(text):
        return IntentFrame(
            role="researcher",
            task_kind="research",
            confidence=0.78,
            needs_plan=True,
            needs_sources=True,
            brief="这是调研/查证任务。优先核实来源和时效,需要最新信息时应搜索或读取权威来源,不要只凭记忆。",
        )

    if _ADVISOR_RE.search(text) and not re.search(r"(修复|改成|改为|写入|提交|推送|部署|上线)", text, re.I):
        return IntentFrame(
            role="advisor",
            task_kind="explain",
            confidence=0.70,
            brief="这是解释/顾问型问题。直接讲清楚,必要时给例子,默认不动文件。",
        )

    if _EXECUTOR_RE.search(text):
        return IntentFrame(
            role="executor",
            task_kind="execute",
            confidence=0.76,
            needs_plan=True,
            should_edit_files=True,
            brief="这是执行型任务。先读现状再动手,复杂任务拆成待办,完成后必须验证并简洁汇报。",
        )

    if _PM_RE.search(text):
        return IntentFrame(
            role="pm",
            task_kind="decide",
            confidence=0.72,
            needs_plan=False,
            brief="这是产品/方向/取舍讨论。先澄清目标、约束和优先级,给出可执行路径,不要急着动文件。",
        )

    # Cowork 模式里的空泛交办,宁可偏执行;Chat 里则偏顾问。
    if getattr(ctx, "coworker", False):
        return IntentFrame(
            role="executor",
            task_kind="execute",
            confidence=0.58,
            needs_plan=True,
            should_edit_files=True,
            brief="当前在 Cowork 模式且意图不完全明确。按执行型任务处理,先做合理假设;若关键方向不明再问。",
        )

    return IntentFrame(
        role="advisor",
        task_kind="clarify",
        confidence=0.52,
        brief="意图不完全明确。先以顾问姿态回应,必要时只问一个会改变方向的澄清问题。",
    )


def intent_prompt_block(frame: IntentFrame) -> str:
    return (
        "【本轮语境判断 · 内部使用,不要向用户复述】\n"
        f"- 角色:{frame.role}\n"
        f"- 任务类型:{frame.task_kind}\n"
        f"- 置信度:{frame.confidence:.2f}\n"
        f"- 需要计划:{'是' if frame.needs_plan else '否'}\n"
        f"- 需要来源:{'是' if frame.needs_sources else '否'}\n"
        f"- 需要确认:{'是' if frame.needs_confirmation else '否'}\n"
        f"- 默认可改文件:{'是' if frame.should_edit_files else '否'}\n"
        f"- 行为提示:{frame.brief}\n"
        "这只是内部姿态,不要在回复里说“我判断你需要我扮演...”。"
    )
