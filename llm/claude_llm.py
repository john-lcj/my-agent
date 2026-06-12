"""Anthropic Claude 的 LLM 实现。

Claude 的 tools 协议与 OpenAI 略有不同,在 adapter 内做转换,对上层透明。
缺 key 或缺 SDK 时给出友好报错,不影响用 MockLLM 跑通流程。
"""
from __future__ import annotations

import os
from typing import Optional

from core.types import CapabilityCall, Message, Role, Step
from llm.streaming import EmitTokenFn


class ClaudeLLM:
    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        api_key_env: str = "ANTHROPIC_API_KEY",
        max_tokens: int = 4096,
    ) -> None:
        self.name = "claude"
        self.model = model
        self.api_key_env = api_key_env
        self.max_tokens = max_tokens
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"缺少环境变量 {self.api_key_env}。请在 .env 中配置,或改用 MockLLM 跑通流程。"
            )
        try:
            from anthropic import AsyncAnthropic
        except ImportError as e:
            raise RuntimeError("未安装 anthropic SDK,请先 `pip install anthropic`。") from e
        self._client = AsyncAnthropic(api_key=api_key)
        return self._client

    async def next_step(
        self,
        messages: list[Message],
        capabilities: list[dict],
        emit_token: Optional[EmitTokenFn] = None,
    ) -> Step:
        client = self._ensure_client()
        system, msgs = _to_claude_messages(messages)
        name_map = {_sanitize(c["name"]): c["name"] for c in capabilities}
        kwargs = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system or None,
            messages=msgs,
            tools=_to_claude_tools(capabilities) or None,
        )
        if emit_token is None:
            resp = await client.messages.create(**kwargs)
            return self._parse_message(resp, name_map)

        text_parts: list[str] = []
        async with client.messages.stream(**kwargs) as stream:
            async for event in stream:
                if event.type == "content_block_delta":
                    delta = event.delta
                    if getattr(delta, "type", None) == "text_delta" and delta.text:
                        text_parts.append(delta.text)
                        await emit_token(delta.text)
            final = await stream.get_final_message()
        return self._parse_message(final, name_map, fallback_text="".join(text_parts))

    @staticmethod
    def _parse_message(resp, name_map: dict, fallback_text: str = "") -> Step:
        text_parts: list[str] = []
        for block in resp.content:
            if block.type == "tool_use":
                return Step(call=CapabilityCall(
                    name=name_map.get(block.name, block.name),
                    args=dict(block.input or {}),
                    intent=" ".join(text_parts).strip(),
                    call_id=block.id or "",
                ))
            if block.type == "text":
                text_parts.append(block.text)
        joined = " ".join(text_parts).strip() or fallback_text
        return Step(text=joined)

    async def summarize(self, text: str) -> str:
        client = self._ensure_client()
        resp = await client.messages.create(
            model=self.model,
            max_tokens=512,
            system="把下面的对话压缩成要点摘要,保留关键事实、决定、未完成事项,去掉寒暄。用简体中文,150字以内。",
            messages=[{"role": "user", "content": text}],
        )
        parts = [b.text for b in resp.content if b.type == "text"]
        return " ".join(parts).strip()


def _to_claude_messages(messages: list[Message]) -> tuple[str, list[dict]]:
    """转换为 Anthropic 协议:tool_use 块发起调用,tool_result 块用 tool_use_id 配对。"""
    system_parts: list[str] = []
    out: list[dict] = []
    for m in messages:
        if m.role == Role.SYSTEM:
            system_parts.append(m.content)
        elif m.role == Role.TOOL:
            out.append({"role": "user", "content": [{
                "type": "tool_result",
                "tool_use_id": m.tool_call_id or "0",
                "content": m.content,
            }]})
        elif m.role == Role.ASSISTANT and m.tool_calls:
            blocks: list[dict] = []
            if m.content:
                blocks.append({"type": "text", "text": m.content})
            for tc in m.tool_calls:
                blocks.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": _sanitize(tc.name),
                    "input": tc.args,
                })
            out.append({"role": "assistant", "content": blocks})
        else:
            role = "assistant" if m.role == Role.ASSISTANT else "user"
            out.append({"role": role, "content": m.content})
    return "\n".join(system_parts), out


def _sanitize(name: str) -> str:
    return name.replace(".", "_")


def _to_claude_tools(capabilities: list[dict]) -> list[dict]:
    return [
        {
            "name": _sanitize(c["name"]),
            "description": c.get("description", ""),
            "input_schema": c.get("schema", {"type": "object", "properties": {}}),
        }
        for c in capabilities
    ]
