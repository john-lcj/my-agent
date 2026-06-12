"""人设与用户画像加载 —— "知道自己是谁、知道我是谁"的静态部分。

从 persona.yaml 读取 agent 身份 + 主人画像,渲染成一段可注入系统提示词的文本。
这是"显式、长期稳定"的认知;动态、会变的事情(临时偏好、最近做过啥)交给
长期记忆(memory.*)在运行时补充。两者叠加,agent 才既有恒定人格又能记住你。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Persona:
    agent_name: str = "助理"
    tagline: str = ""
    personality: str = ""
    owner_name: str = ""
    call_me: str = ""
    owner_about: str = ""
    owner_preferences: list[str] = field(default_factory=list)

    def to_prompt(self) -> str:
        """渲染成注入系统提示词的"身份卡片"。"""
        lines = [f"# 你的身份\n你叫「{self.agent_name}」"]
        if self.tagline:
            lines[-1] += f",{self.tagline}。"
        if self.personality:
            lines.append(self.personality.strip())

        owner_bits = []
        if self.owner_name:
            call = f"(称呼为「{self.call_me}」)" if self.call_me else ""
            owner_bits.append(f"你的主人是「{self.owner_name}」{call}。")
        if self.owner_about:
            owner_bits.append(self.owner_about.strip())
        if self.owner_preferences:
            owner_bits.append("他的偏好:")
            owner_bits += [f"- {p}" for p in self.owner_preferences]
        if owner_bits:
            lines.append("\n# 关于你的主人\n" + "\n".join(owner_bits))
        return "\n".join(lines)


def load_persona(path: str = "persona.yaml") -> "Persona | None":
    """加载 persona.yaml;文件缺失或解析失败返回 None(回退到通用人设)。"""
    if not os.path.isfile(path):
        return None
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"[persona] 加载 {path} 失败: {e}")
        return None

    agent = data.get("agent", {}) or {}
    owner = data.get("owner", {}) or {}
    return Persona(
        agent_name=agent.get("name", "助理"),
        tagline=agent.get("tagline", ""),
        personality=agent.get("personality", ""),
        owner_name=owner.get("name", ""),
        call_me=owner.get("call_me", ""),
        owner_about=owner.get("about", ""),
        owner_preferences=owner.get("preferences", []) or [],
    )
