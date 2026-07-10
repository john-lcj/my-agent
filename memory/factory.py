"""长期记忆工厂 —— 按配置组装 HybridMemory(SQLite + Vector)。"""
from __future__ import annotations

import os

from config import Config
from memory.hybrid import HybridMemory
from memory.longterm_sqlite import SQLiteMemory
from memory.vector import MockEmbed, VectorMemory, openai_embed_fn


def _build_embed_fn():
    provider = (os.environ.get("AGENT_EMBED_PROVIDER")
                or getattr(Config, "EMBED_PROVIDER", None)
                or "openai").lower()
    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
        if key:
            return openai_embed_fn(api_key=key)
        return None
    if provider == "mock" and (os.environ.get("AGENT_EMBED_ALLOW_MOCK") == "1"
                                or os.environ.get("PYTEST_CURRENT_TEST")):
        return MockEmbed()
    raise RuntimeError("A real embedding provider is required; set OPENAI_API_KEY or explicitly allow mock embeddings for tests")


def build_longterm(log_dir: str | None = None) -> HybridMemory:
    base = log_dir or Config.LOG_DIR
    os.makedirs(base, exist_ok=True)
    keyword = SQLiteMemory(db_path=os.path.join(base, "memory.db"))
    embed_fn = _build_embed_fn()
    semantic = VectorMemory(embed_fn=embed_fn, db_path=os.path.join(base, "vectors.db")) if embed_fn else None
    return HybridMemory(keyword=keyword, semantic=semantic)
