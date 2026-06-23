"""评测质检员 —— 用 LLM 对开放式产出打质量分(确定性判据覆盖不了的"好不好")。

判据写在用例的 expect.judge(一句话评分标准 + 阈值);质检员读任务+产出,
按标准给 0~10 分。默认用"判断脑"(AGENT_JUDGE_MODEL,reasoner 档),
和交付校验同一套思路。离线/未配模型/调用失败时返回 None(该用例的 judge 项跳过、不误判)。
"""
from __future__ import annotations

import re
from typing import Optional


async def judge_quality(task: str, output: str, rubric: str,
                        threshold: int = 6) -> Optional[dict]:
    """返回 {score:int, passed:bool, comment:str};无法判定返回 None。"""
    try:
        from llm.factory import build_role_llm, build_llm
        from core.types import Message, Role
    except Exception:
        return None
    llm = None
    try:
        llm = build_role_llm("judge") or build_llm()
    except Exception:
        return None
    if llm is None:
        return None
    prompt = (
        f"任务:{task}\n\n产出:\n{(output or '')[:4000]}\n\n"
        f"评分标准:{rubric}\n\n"
        "请按标准给这份产出打 0~10 分(10=完全达标)。"
        "**第一行只输出一个 0~10 的整数分数**,第二行用一句话说理由。")
    try:
        step = await llm.next_step(
            [Message(role=Role.SYSTEM, content="你是严格的评测质检员,只按标准客观打分。"),
             Message(role=Role.USER, content=prompt)], [], None)
        text = (getattr(step, "text", "") or "").strip()
    except Exception:
        return None
    m = re.search(r"\d{1,2}", text)
    if not m:
        return None
    score = max(0, min(10, int(m.group())))
    comment = text.split("\n", 1)[1].strip() if "\n" in text else ""
    return {"score": score, "passed": score >= threshold, "comment": comment[:200]}
