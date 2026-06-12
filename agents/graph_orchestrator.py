"""DAG 执行器 —— 按依赖图调度专家协作。

核心能力:
- **拓扑分层执行**:同层(依赖已满足)的节点并行跑,层与层之间串行。
- **共享黑板(blackboard)**:每个节点的产物/状态都登记在黑板上;下游节点执行前,
  会把它依赖的上游产出喂进任务上下文 —— 专家于是能"接着上一个人的产出干"。
- **失败阻断**:某节点失败 → 其所有下游标记为 blocked、不再执行(避免在错误基础上空跑)。
- (Phase 2)**验证/返修**:产出后对照 acceptance 自检,不达标做一次有界返修。

执行器只依赖 worker_registry.get(name).run(task) 这一接口,与具体专家实现解耦;
事件通过 on_event 回调推出去,供可观测层渲染"执行计划图"。
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

from agents.plan_graph import PlanGraph, PlanNode

# verifier(node, output) -> (ok: bool, reason: str);可同步可异步。
Verifier = Callable[[PlanNode, str], object]
OnEvent = Callable[[dict], object]

_DONE = ("done", "revised")


class GraphOrchestrator:
    def __init__(
        self,
        worker_registry,
        *,
        on_event: Optional[OnEvent] = None,
        verifier: Optional[Verifier] = None,
        max_revisions: int = 1,
    ) -> None:
        self._workers = worker_registry
        self._on_event = on_event
        self._verifier = verifier
        self._max_revisions = max(0, int(max_revisions))

    async def run(self, graph: PlanGraph, original_task: str,
                  captain_context: str = "") -> dict:
        bb: dict[str, dict] = {
            n.id: {"status": "pending", "output": "", "agent": n.agent,
                   "sub_task": n.sub_task, "revisions": 0}
            for n in graph.nodes
        }
        await self._emit({"type": "plan", "nodes": [
            {"id": n.id, "agent": n.agent, "sub_task": n.sub_task,
             "depends_on": n.depends_on} for n in graph.nodes
        ], "reason": graph.reason})

        for layer in graph.layers():
            runnable, blocked = [], []
            for n in layer:
                (runnable if self._deps_ok(n, bb) else blocked).append(n)
            for n in blocked:
                bb[n.id]["status"] = "blocked"
                bb[n.id]["output"] = "上游失败,已跳过"
                await self._emit({"type": "node", "id": n.id, "status": "blocked"})
            if runnable:
                await asyncio.gather(*[
                    self._run_node(n, original_task, captain_context, bb) for n in runnable
                ])

        results = [
            (bb[n.id]["agent"] or "captain", bb[n.id]["output"])
            for n in graph.nodes
            if bb[n.id]["status"] in ("done", "revised", "failed")
        ]
        return {"blackboard": bb, "results": results, "graph": graph}

    # ── 内部 ──────────────────────────────────────────────────────────────────
    def _deps_ok(self, node: PlanNode, bb: dict) -> bool:
        return all(bb.get(d, {}).get("status") in _DONE for d in node.depends_on)

    async def _run_node(self, node: PlanNode, original_task: str,
                        captain_context: str, bb: dict) -> None:
        bb[node.id]["status"] = "running"
        await self._emit({"type": "node", "id": node.id, "status": "running",
                          "agent": node.agent})

        output = await self._invoke(node, original_task, captain_context, bb)
        ok = output is not None and "执行失败" not in output and not output.startswith("执行异常")

        # Phase 2:验证 + 有界返修
        if ok and self._verifier is not None and node.acceptance:
            ok, output = await self._verify_and_revise(
                node, output, original_task, captain_context, bb)

        if ok:
            status = "revised" if bb[node.id]["revisions"] > 0 else "done"
        else:
            status = "failed"
        bb[node.id]["status"] = status
        bb[node.id]["output"] = output or "(无输出)"
        await self._emit({"type": "node", "id": node.id, "status": status,
                          "agent": node.agent})

    async def _invoke(self, node: PlanNode, original_task: str,
                      captain_context: str, bb: dict) -> str:
        worker = self._workers.get(node.agent) if node.agent else None
        if worker is None:
            # 未指定专家(或交给 Captain):此处不执行,留作汇总时由 Captain 处理。
            return f"(待 Captain 直接处理){node.sub_task}"
        packed = self._pack(node, original_task, captain_context, bb)
        try:
            return await worker.run(packed)
        except Exception as e:
            return f"执行异常: {e}"

    async def _verify_and_revise(self, node, output, original_task, captain_context, bb):
        for _ in range(self._max_revisions + 1):
            ok, reason = await _maybe_await(self._verifier(node, output))
            if ok:
                return True, output
            if bb[node.id]["revisions"] >= self._max_revisions:
                return False, output
            bb[node.id]["revisions"] += 1
            await self._emit({"type": "node", "id": node.id, "status": "revising",
                              "reason": reason})
            worker = self._workers.get(node.agent) if node.agent else None
            if worker is None:
                return False, output
            retry_task = self._pack(node, original_task, captain_context, bb,
                                    revise_reason=reason, prev_output=output)
            try:
                output = await worker.run(retry_task)
            except Exception as e:
                return False, f"返修异常: {e}"
        return True, output

    @staticmethod
    def _pack(node: PlanNode, original_task: str, captain_context: str, bb: dict,
              *, revise_reason: str = "", prev_output: str = "") -> str:
        parts = [f"【主人原始任务】\n{original_task.strip()}"]
        if captain_context.strip():
            parts.append(f"【Captain 上下文】\n{captain_context.strip()}")
        ups = [d for d in node.depends_on if bb.get(d, {}).get("output")]
        if ups:
            up_text = "\n\n".join(f"[来自 {d}]\n{bb[d]['output'][:1500]}" for d in ups)
            parts.append(f"【上游已完成的产出(请据此衔接,不要重复)】\n{up_text}")
        if node.acceptance:
            parts.append(f"【验收标准(必须满足)】\n{node.acceptance}")
        if revise_reason:
            parts.append(f"【上一版未达标,原因】\n{revise_reason}\n"
                         f"【你上一版的产出(请针对性修正,而非重写)】\n{(prev_output or '')[:1500]}")
        parts.append(f"【请你执行】\n{node.sub_task.strip()}")
        return "\n\n".join(parts)

    async def _emit(self, payload: dict) -> None:
        if self._on_event is None:
            return
        try:
            await _maybe_await(self._on_event(payload))
        except Exception:
            pass


async def _maybe_await(value):
    if hasattr(value, "__await__"):
        return await value
    return value
