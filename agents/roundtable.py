"""圆桌会议 —— 高级版本,支持打断/可见开关/主持人总结/Markdown 导出。

核心设计:
  - RTAgentConfig: 每个参与者的完整配置(模型/系统 prompt/可见开关)
  - AdvancedRoundtable.run(): 主循环,流式通过 on_event 回调推事件
  - _should_interrupt(): 每轮发言前检查是否有人想打断(LLM yes/no 判断)
  - can_see_others=False 的 agent 只看到自己的历史发言,不受他人影响
  - 会议结束后自动调 _generate_summary(),由独立 Moderator LLM 输出总结
  - export_markdown(): 纯静态方法,把记录转成规范的 Markdown

事件流(推给 on_event):
  {"type":"rt_interrupt_intent", "agent_id":..., "agent_name":..., "target_name":...}
  {"type":"rt_speaking", "agent_id":..., "agent_name":..., "agent_color":...}
  {"type":"rt_message",  "agent_id":..., "agent_name":..., "role":...,
   "content":..., "msg_type":"normal"|"interrupt", "turn":n, "agent_color":...}
  {"type":"rt_phase",    "phase":"diverge"|"debate"|"converge"}
  {"type":"rt_summary",  "content":...}
  {"type":"rt_done",     "turns":n, "stopped":"..."}
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional

from core.types import Message, Role

# 默认颜色映射(按 id)
AGENT_COLORS: dict[str, str] = {
    "pm":        "#5b8ef0",
    "engineer":  "#4caf79",
    "risk":      "#e85555",
    "creative":  "#9b72cf",
    "devil":     "#f5874c",
    "marketing": "#e05c9b",
    "trade":     "#4cbfb0",
    "custom":    "#f5c842",
}

# 预设 agent 系统 prompt
PRESET_PROMPTS: dict[str, str] = {
    "pm": (
        "你是经验丰富的产品经理。关注用户需求、产品价值和市场机会。"
        "思考产品路线图、优先级排序和用户体验。发言简短有力,聚焦 Why 和 What。"
    ),
    "engineer": (
        "你是资深软件工程师。关注技术可行性、实现挑战、系统设计和代码质量。"
        "识别技术债务和可扩展性问题。发言聚焦 How 和技术风险。"
    ),
    "risk": (
        "你是风险评估师。职责是发现潜在风险、最坏情况和合规隐患。"
        "对每个方案都要思考:它可能以什么方式失败?影响有多大?缓解措施是什么?"
    ),
    "creative": (
        "你是创意总监。思维发散,善于跳出常规框架提出创新方案。"
        "引导团队思考还没有人想到的可能性,用'如果...会怎样'的方式提问。"
    ),
    "devil": (
        "你是魔鬼代言人。你的职责是挑战一切假设、质疑所有'共识'。"
        "不是为了抬杠,而是为了发现盲点。每次发言都要找到当前讨论最薄弱的环节。"
    ),
    "marketing": (
        "你是营销专家。关注市场定位、用户获取、品牌信息和增长策略。"
        "思考如何讲好这个故事、触达目标用户、在竞争中差异化。"
    ),
    "trade": (
        "你是外贸专员。关注国际市场、跨境合规、贸易壁垒和本地化需求。"
        "从全球视角评估方案,识别不同市场的特殊要求。"
    ),
    "custom": "你是一位思维独立的讨论参与者。发表你真实的看法,简洁有力。",
}

# 角色打断优先级(越高越先抢到发言权)
INTERRUPT_PRIORITY: dict[str, int] = {
    "devil": 10,
    "risk": 8,
    "creative": 6,
    "pm": 5,
    "marketing": 5,
    "engineer": 4,
    "trade": 4,
}

# 每轮检查该角色是否想打断的概率
INTERRUPT_CHECK_RATE: dict[str, float] = {
    "devil": 1.0,
    "risk": 0.85,
    "creative": 0.65,
    "pm": 0.5,
    "marketing": 0.45,
    "engineer": 0.4,
    "trade": 0.4,
}

PHASE_HINTS: dict[str, str] = {
    "diverge": "发散期:尽可能提出新角度、用户群、假设与可能性,不要急于达成一致。",
    "debate": "辩论期:质疑他人观点、找逻辑漏洞,用具体论据反驳或补充。",
    "converge": "收敛期:推动形成可执行结论,明确「我们决定…因为…」,避免空泛表态。",
}


@dataclass
class RTAgentConfig:
    id: str
    name: str
    role: str
    model: str                   # "deepseek" / "claude" / "openai" / "mock"
    system_prompt: str = ""
    can_see_others: bool = True  # False = 只看自己发言,不受他人影响
    can_interrupt: bool = True   # 是否可举手打断他人
    interrupt_priority: int = 5
    color: str = "#888888"

    def __post_init__(self):
        if not self.system_prompt:
            self.system_prompt = PRESET_PROMPTS.get(self.id, PRESET_PROMPTS["custom"])
        if not self.color:
            self.color = AGENT_COLORS.get(self.id, "#888888")
        if self.interrupt_priority == 5 and self.id in INTERRUPT_PRIORITY:
            self.interrupt_priority = INTERRUPT_PRIORITY[self.id]


OnEvent = Callable[[dict], Awaitable[None]]


class AdvancedRoundtable:
    def __init__(self, llm_factory: Callable[[str], Any], max_turns: int = 12) -> None:
        self._llm_factory = llm_factory
        self.max_turns = max_turns

    async def run(
        self,
        configs: list[dict | RTAgentConfig],
        topic: str,
        on_event: Optional[OnEvent] = None,
        max_turns: Optional[int] = None,
        enable_interrupt: bool = True,
        user_queue: Optional[asyncio.Queue] = None,
        mode: str = "brainstorm",
        goal: str = "",
    ) -> dict:
        max_turns = max_turns or self.max_turns
        mode = mode if mode in ("brainstorm", "discussion") else "brainstorm"
        goal = (goal or "").strip()
        # 标准化配置
        agent_cfgs: list[RTAgentConfig] = []
        for c in configs:
            if isinstance(c, dict):
                agent_cfgs.append(RTAgentConfig(
                    id=c.get("id", "custom"),
                    name=c.get("name", "Agent"),
                    role=c.get("role", c.get("name", "Agent")),
                    model=c.get("model", "deepseek"),
                    system_prompt=c.get("system_prompt", ""),
                    can_see_others=c.get("can_see_others", True),
                    can_interrupt=c.get("can_interrupt", True),
                    interrupt_priority=c.get(
                        "interrupt_priority",
                        INTERRUPT_PRIORITY.get(c.get("id", ""), 5),
                    ),
                    color=c.get("color", AGENT_COLORS.get(c.get("id", ""), "#888888")),
                ))
            else:
                agent_cfgs.append(c)

        if not agent_cfgs:
            return {"transcript": [], "summary": "", "turns": 0, "stopped": "无参与者"}

        # 为每个 agent 建 LLM 实例
        llms = {cfg.id: self._llm_factory(cfg.model) for cfg in agent_cfgs}

        conversation: list[Message] = []
        stopped = "达到最大轮数"
        turn = 0
        last_msg: Optional[Message] = None
        last_phase: Optional[str] = None

        async def emit(evt: dict):
            if on_event:
                await on_event(evt)

        while turn < max_turns:
            user_msg = await self._drain_user_queue(user_queue, conversation, emit, turn)
            if user_msg:
                last_msg = user_msg

            phase = self._phase(turn, max_turns, mode)
            if phase != last_phase and mode == "brainstorm":
                await emit({"type": "rt_phase", "phase": phase, "hint": PHASE_HINTS.get(phase, "")})
                last_phase = phase

            scheduled_idx = turn % len(agent_cfgs)
            interrupt_cfg: Optional[RTAgentConfig] = None
            reply_to: Optional[Message] = None

            if enable_interrupt and last_msg and turn > 0:
                interrupt_cfg, reply_to = await self._find_interrupter(
                    agent_cfgs, llms, scheduled_idx, last_msg, topic, emit,
                )

            speaker_cfg = interrupt_cfg if interrupt_cfg else agent_cfgs[scheduled_idx]
            msg_type = "interrupt" if interrupt_cfg else "normal"
            is_opening = not interrupt_cfg and turn < len(agent_cfgs)

            await emit({
                "type": "rt_speaking",
                "agent_id": speaker_cfg.id,
                "agent_name": speaker_cfg.name,
                "agent_color": speaker_cfg.color,
                "msg_type": msg_type,
            })

            visible = self._build_context(speaker_cfg, conversation)
            content = await self._generate(
                speaker_cfg,
                llms[speaker_cfg.id],
                topic,
                visible,
                phase=phase if mode == "brainstorm" else "free",
                goal=goal,
                is_interrupt=bool(interrupt_cfg),
                reply_to=reply_to if interrupt_cfg else None,
                is_opening=is_opening,
            )

            msg = Message(role=Role.ASSISTANT, content=content, name=speaker_cfg.name)
            conversation.append(msg)
            last_msg = msg
            turn += 1

            await emit({
                "type": "rt_message",
                "agent_id": speaker_cfg.id,
                "agent_name": speaker_cfg.name,
                "role": speaker_cfg.role,
                "content": content,
                "msg_type": msg_type,
                "turn": turn,
                "agent_color": speaker_cfg.color,
                "phase": phase if mode == "brainstorm" else None,
            })

            if mode == "brainstorm" and turn >= 6 and turn % 3 == 0:
                if await self._ready_to_conclude(topic, conversation, llms[agent_cfgs[0].id], goal):
                    stopped = "已形成可执行结论"
                    break

        # 主持人总结
        await emit({"type": "rt_speaking", "agent_id": "moderator",
                    "agent_name": "主持人", "agent_color": "#cccccc"})
        summary = await self._generate_summary(
            topic, conversation, llms.get(agent_cfgs[0].id), goal=goal, mode=mode,
        )
        await emit({"type": "rt_summary", "content": summary})
        await emit({"type": "rt_done", "turns": turn, "stopped": stopped})

        return {
            "transcript": conversation,
            "summary": summary,
            "turns": turn,
            "stopped": stopped,
            "configs": agent_cfgs,
        }

    # ── 核心方法 ───────────────────────────────────────────────────────────────

    async def _drain_user_queue(
        self,
        user_queue: Optional[asyncio.Queue],
        conversation: list[Message],
        emit: Callable[[dict], Awaitable[None]],
        turn: int,
    ) -> Optional[Message]:
        """将用户通过 WS 插入的发言写入讨论记录。"""
        if not user_queue:
            return None
        last: Optional[Message] = None
        while True:
            try:
                user_text = user_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            text = (user_text or "").strip()
            if not text:
                continue
            msg = Message(role=Role.USER, content=text, name="你")
            conversation.append(msg)
            last = msg
            await emit({
                "type": "rt_message",
                "agent_id": "user",
                "agent_name": "你",
                "role": "主持人",
                "content": text,
                "msg_type": "user_interrupt",
                "turn": turn,
                "agent_color": "#D97757",
            })
        return last

    async def _find_interrupter(
        self,
        agent_cfgs: list[RTAgentConfig],
        llms: dict,
        scheduled_idx: int,
        last_msg: Message,
        topic: str,
        emit: Callable[[dict], Awaitable[None]],
    ) -> tuple[Optional[RTAgentConfig], Optional[Message]]:
        """并行询问非当前发言者是否举手打断,按优先级选出一人。"""
        async def _probe(i: int, cfg: RTAgentConfig) -> Optional[RTAgentConfig]:
            if i == scheduled_idx or not cfg.can_interrupt:
                return None
            rate = INTERRUPT_CHECK_RATE.get(cfg.id, 0.45)
            if random.random() > rate:
                return None
            if await self._should_interrupt(cfg, llms[cfg.id], last_msg, topic):
                return cfg
            return None

        results = await asyncio.gather(
            *[_probe(i, cfg) for i, cfg in enumerate(agent_cfgs)]
        )
        candidates = [c for c in results if c]
        if not candidates:
            return None, None

        winner = max(candidates, key=lambda c: c.interrupt_priority)
        await emit({
            "type": "rt_interrupt_intent",
            "agent_id": winner.id,
            "agent_name": winner.name,
            "agent_color": winner.color,
            "target_name": last_msg.name,
            "target_preview": (last_msg.content or "")[:120],
        })
        return winner, last_msg

    async def _should_interrupt(
        self, cfg: RTAgentConfig, llm, last_msg: Message, topic: str
    ) -> bool:
        """让 agent 决定是否举手打断。"""
        prompt = (
            f"议题:{topic}\n"
            f"刚才「{last_msg.name}」说:{last_msg.content[:300]}\n\n"
            f"你是「{cfg.role}」({cfg.name})。"
            f"你是否必须立即举手打断,以纠正错误、补充关键信息或提出强烈反对?\n"
            f"只有当你确实有重要且不同的观点时才打断。只回答 yes 或 no。"
        )
        try:
            step = await llm.next_step(
                [Message(role=Role.SYSTEM, content=cfg.system_prompt),
                 Message(role=Role.USER, content=prompt)],
                [],
            )
            text = (step.text or "").strip().lower()
            return text.startswith("y") or text.startswith("是") or "打断" in text or "必须" in text
        except Exception:
            return False

    def _phase(self, turn: int, max_turns: int, mode: str) -> str:
        if mode != "brainstorm" or max_turns <= 0:
            return "free"
        ratio = turn / max_turns
        if ratio < 0.35:
            return "diverge"
        if ratio < 0.7:
            return "debate"
        return "converge"

    async def _ready_to_conclude(
        self, topic: str, conversation: list[Message], llm, goal: str,
    ) -> bool:
        """LLM 判断讨论是否已可形成明确结论。"""
        if len(conversation) < 6:
            return False
        transcript = "\n".join(
            f"【{m.name}】{m.content}" for m in conversation[-10:]
        )
        prompt = (
            f"议题:{topic}\n"
            f"期望产出:{goal or '形成明确、可执行的结论'}\n\n"
            f"近期讨论:\n{transcript}\n\n"
            f"是否已有足够信息形成明确结论(含具体建议或决策,而非泛泛而谈)?"
            f"只回答 yes 或 no。"
        )
        try:
            step = await llm.next_step([Message(role=Role.USER, content=prompt)], [])
            text = (step.text or "").strip().lower()
            return text.startswith("y") or text.startswith("是")
        except Exception:
            return False

    def _build_context(self, cfg: RTAgentConfig, full: list[Message]) -> list[Message]:
        """can_see_others=False 时,只返回该 agent 自己的发言(仍包含用户插话)。"""
        if cfg.can_see_others:
            return full
        return [m for m in full if m.name == cfg.name or m.role == Role.USER]

    async def _generate(
        self,
        cfg: RTAgentConfig,
        llm,
        topic: str,
        context: list[Message],
        phase: str = "free",
        goal: str = "",
        is_interrupt: bool = False,
        reply_to: Optional[Message] = None,
        is_opening: bool = False,
    ) -> str:
        transcript = "\n".join(
            f"【{m.name}】{m.content}" for m in context[-12:]
        )
        parts = [f"议题:{topic}"]
        if goal:
            parts.append(f"期望产出:{goal}")
        if phase in PHASE_HINTS:
            parts.append(f"当前阶段:{PHASE_HINTS[phase]}")
        parts.append(f"\n讨论记录:\n{transcript or '(尚无发言)'}\n")

        if is_interrupt and reply_to:
            parts.append(
                f"你举手打断了「{reply_to.name}」的发言。TA 说:{reply_to.content[:400]}\n"
                f"请直接回应其核心观点:指出问题、强烈反对或补充关键遗漏。"
                f"不要重复已有内容,2-4 句话,开门见山。"
            )
        elif is_opening:
            parts.append(
                f"你是「{cfg.role}」。请先亮明你的开场立场(2-3 句话):"
                f"对议题的核心判断或首要关注点。"
            )
        else:
            parts.append(
                f"你是「{cfg.role}」。请用 2-4 句话发表你的下一个观点。"
                f"要具体、可验证,避免空话。直接说观点,不要以'我认为'开头。"
            )

        messages = [
            Message(role=Role.SYSTEM, content=cfg.system_prompt),
            Message(role=Role.USER, content="\n".join(parts)),
        ]
        step = await llm.next_step(messages, [])
        return step.text or "(无发言)"

    async def _generate_summary(
        self,
        topic: str,
        conversation: list[Message],
        llm,
        goal: str = "",
        mode: str = "brainstorm",
    ) -> str:
        if not conversation:
            return "本次圆桌无实质性发言。"
        transcript = "\n".join(f"【{m.name}】{m.content}" for m in conversation)
        if mode == "brainstorm":
            prompt = (
                f"你是会议主持人。请基于以下圆桌讨论输出可执行的头脑风暴结论:\n\n"
                f"议题:{topic}\n"
                f"期望产出:{goal or '明确、可落地的决策或方案'}\n\n"
                f"{transcript}\n\n"
                f"用 Markdown 输出,必须包含:\n"
                f"## 结论\n一句话写清最终决策或判断(不要模糊措辞)\n\n"
                f"## 理由\n3-5 条支撑论据(具体,可验证)\n\n"
                f"## 主要分歧\n仍未达成一致的关键争议\n\n"
                f"## 下一步行动\n3 条具体行动,含优先级\n\n"
                f"## 待验证假设\n需要数据或实验才能确认的点"
            )
        else:
            prompt = (
                f"你是会议主持人。请对以下圆桌讨论做一个结构化总结:\n\n"
                f"议题:{topic}\n\n{transcript}\n\n"
                f"要求:①3-5条核心共识 ②主要分歧点 ③建议的下一步行动。用 Markdown 格式输出。"
            )
        try:
            step = await llm.next_step([Message(role=Role.USER, content=prompt)], [])
            return step.text or "总结生成失败。"
        except Exception as e:
            return f"总结生成失败:{e}"

    # ── 导出 ──────────────────────────────────────────────────────────────────

    @staticmethod
    def export_markdown(
        topic: str,
        configs: list[RTAgentConfig],
        conversation: list[Message],
        summary: str,
    ) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        names = ", ".join(c.name for c in configs)
        lines = [
            f"# 圆桌会议记录\n",
            f"**议题:** {topic}  ",
            f"**时间:** {now}  ",
            f"**参与者:** {names}\n",
            "---\n",
            "## 会议发言\n",
        ]
        for i, msg in enumerate(conversation, 1):
            cfg = next((c for c in configs if c.name == msg.name), None)
            role_label = f"({cfg.role})" if cfg else ""
            lines.append(f"**[第{i}轮] {msg.name}** {role_label}\n")
            lines.append(f"> {msg.content}\n")
        lines += ["\n---\n", "## 主持人总结\n", summary]
        return "\n".join(lines)


# ── 向后兼容:保留旧 Roundtable 类 ─────────────────────────────────────────────

class Roundtable:
    """旧版圆桌(向后兼容),内部委托给 AdvancedRoundtable。"""

    def __init__(self, moderator=None, max_turns: int = 12) -> None:
        self.moderator = moderator
        self.max_turns = max_turns

    async def run(self, agents: list, task: str) -> dict:
        from agents.moderator import RoundRobinModerator
        from governance.budget import BudgetGovernor

        moderator = self.moderator or RoundRobinModerator()
        conversation: list[Message] = []
        budget = BudgetGovernor(max_steps=self.max_turns)
        stopped = "达到最大轮数"
        turn = 0
        while not budget.exceeded():
            budget.charge_step()
            speaker = moderator.next_speaker(agents, turn)
            msg = await speaker.step(task, conversation)
            conversation.append(msg)
            turn += 1
            if moderator.has_converged(conversation):
                stopped = "讨论已收敛"
                break
        return {"transcript": conversation, "turns": turn, "stopped": stopped}
