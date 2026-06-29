"""人设与用户画像加载 —— "知道自己是谁、知道我是谁"的静态部分。

从 persona.yaml 读取 agent 身份（agent 段）；
从 data/owner.json 读取主人档案（owner 段，不进 git）。
两者合并渲染成注入系统提示词的文本。
data/ 已在 .gitignore，git reset --hard 不会清空用户数据。
"""
from __future__ import annotations

import json
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


def _owner_json_path() -> str:
    """返回 data/owner.json 的绝对路径（相对于项目根）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "data", "owner.json")


def _migrate_owner_from_yaml(yaml_path: str, owner_json: str) -> dict:
    """
    如果 persona.yaml 含 owner 段且 owner.json 不存在，
    自动迁移到 owner.json 并从 yaml 清除 owner 段。
    返回迁移出的 owner dict（可能为空）。
    """
    try:
        import yaml
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        owner = data.get("owner", {}) or {}
        if not owner:
            return {}
        # 写入 owner.json
        os.makedirs(os.path.dirname(owner_json), exist_ok=True)
        with open(owner_json, "w", encoding="utf-8") as f:
            json.dump(owner, f, ensure_ascii=False, indent=2)
        # 从 persona.yaml 移除 owner 段
        data.pop("owner", None)
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
        print("[persona] 已将 owner 档案从 persona.yaml 迁移至 data/owner.json")
        return owner
    except Exception as e:
        print(f"[persona] 迁移 owner 失败: {e}")
        return {}


def load_owner() -> dict:
    """读取 data/owner.json，不存在则返回空 dict。"""
    path = _owner_json_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception as e:
        print(f"[persona] 读取 owner.json 失败: {e}")
        return {}


def save_owner(owner: dict) -> None:
    """写入 data/owner.json。"""
    path = _owner_json_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(owner, f, ensure_ascii=False, indent=2)


def load_persona(path: str = "persona.yaml") -> "Persona | None":
    """
    加载 persona：
    - agent 身份从 persona.yaml 读取
    - owner 档案从 data/owner.json 读取
    - 若 owner.json 不存在但 persona.yaml 含 owner 段，自动迁移
    文件缺失或解析失败返回 None（回退到通用人设）。
    """
    # 解析 persona.yaml（agent 段）
    agent: dict = {}
    if os.path.isfile(path):
        try:
            import yaml
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            agent = data.get("agent", {}) or {}
        except Exception as e:
            print(f"[persona] 加载 {path} 失败: {e}")

    # 读取 owner 档案
    owner_json = _owner_json_path()
    if not os.path.isfile(owner_json) and os.path.isfile(path):
        # 尝试从旧 persona.yaml owner 段迁移
        owner = _migrate_owner_from_yaml(path, owner_json)
    else:
        owner = load_owner()

    # agent 和 owner 都空时返回 None
    if not agent and not owner:
        return None

    return Persona(
        agent_name=agent.get("name", "助理"),
        tagline=agent.get("tagline", ""),
        personality=agent.get("personality", ""),
        owner_name=owner.get("name", ""),
        call_me=owner.get("call_me", ""),
        owner_about=owner.get("about", ""),
        owner_preferences=owner.get("preferences", []) or [],
    )
