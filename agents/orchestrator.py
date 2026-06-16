"""多 agent 编排策略。

每种协同模式都是 Orchestration 的一种实现。返回 {"transcript": [...]}。
Hierarchical(主管拆解→下属执行→汇总)已实现。
"""
from __future__ import annotations

from core.types import Message


class Sequential:
    """流水线编排:按顺序把任务交给每个 agent,后者能看到前者的产出。"""

    async def run(self, agents: list, task: str) -> dict:
        conversation: list[Message] = []
        for agent in agents:
            msg = await agent.step(task, conversation)
            conversation.append(msg)
        return {"transcript": conversation, "turns": len(conversation)}


class Hierarchical:
    """分层编排:第一个 agent 是主管,其余是下属。

    主管用 ChatAgent.step 把任务分解成若干子任务,分发给下属执行,
    最后汇总所有下属的产出给出综合结论。
    """

    async def run(self, agents: list, task: str) -> dict:
        if not agents:
            return {"transcript": [], "turns": 0}
        manager, workers = agents[0], agents[1:]
        transcript: list[Message] = []

        # 1. 主管拆解任务
        breakdown_prompt = f"你是主管,请把以下任务拆分成 {len(workers)} 个子任务(每行一个,不要编号):\n{task}"
        breakdown_msg = await manager.step(breakdown_prompt, [])
        transcript.append(breakdown_msg)

        sub_tasks = [line.strip() for line in breakdown_msg.content.splitlines() if line.strip()]
        # 如果主管没输出足够的行,用原任务填充
        while len(sub_tasks) < len(workers):
            sub_tasks.append(task)

        # 2. 各下属执行子任务
        worker_results: list[Message] = []
        for worker, sub in zip(workers, sub_tasks):
            msg = await worker.step(sub, [])
            worker_results.append(msg)
            transcript.append(msg)

        # 3. 主管汇总
        summary_ctx = transcript[:]
        summary_msg = await manager.step("请综合以上所有下属的输出,给出最终结论。", summary_ctx)
        transcript.append(summary_msg)

        return {"transcript": transcript, "turns": len(transcript)}
