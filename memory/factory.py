"""长期记忆工厂 —— 按配置组装 HybridMemory(SQLite + Vector)。"""
from __future__ import annotations

import os

from config import Config
from memory.hybrid import HybridMemory
from memory.longterm_sqlite import SQLiteMemory
from memory.vector import MockEmbed, VectorMemory, openai_embed_fn


def _build_embed_fn():
    provider = (getattr(Config, "EMBED_PROVIDER", None) or os.environ.get(
        "AGENT_EMBED_PROVIDER", "mock"
    )).lower()
    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
        if key:
            return openai_embed_fn(api_key=key)
    return MockEmbed()


def build_longterm(log_dir: str | None = None) -> HybridMemory:
    base = log_dir or Config.LOG_DIR
    os.makedirs(base, exist_ok=True)
    keyword = SQLiteMemory(db_path=os.path.join(base, "memory.db"))
    semantic = VectorMemory(
        embed_fn=_build_embed_fn(),
        db_path=os.path.join(base, "vectors.db"),
    )
    return HybridMemory(keyword=keyword, semantic=semantic)
