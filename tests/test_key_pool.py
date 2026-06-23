"""DeepSeek 多 key 池:把并行子代理分散到多个 key,绕开单 key 并发上限。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_key_pool_reads_numbered_and_csv():
    from llm.factory import deepseek_key_pool
    saved = {k: os.environ.get(k) for k in
             ("DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY_2", "DEEPSEEK_API_KEY_3", "DEEPSEEK_API_KEYS")}
    try:
        for k in saved:
            os.environ.pop(k, None)
        os.environ["DEEPSEEK_API_KEY"] = "k1"
        os.environ["DEEPSEEK_API_KEY_2"] = "k2"
        os.environ["DEEPSEEK_API_KEY_3"] = "k3"
        assert deepseek_key_pool() == ["k1", "k2", "k3"]
        # 逗号分隔 + 去重保序
        os.environ["DEEPSEEK_API_KEYS"] = "ka, kb, k1"
        assert deepseek_key_pool() == ["ka", "kb", "k1", "k2", "k3"]
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_llm_stores_pool():
    from llm.openai_llm import OpenAILLM
    llm = OpenAILLM(model="x", api_keys=["k1", "k2", "k3"])
    assert llm._keys == ["k1", "k2", "k3"]


def test_pick_client_round_robins_keys():
    """每次取客户端轮换到下一个 key,且同 key 复用同一客户端。"""
    try:
        import openai  # noqa: F401
    except Exception:
        return  # 沙箱无 openai SDK 时跳过
    from llm.openai_llm import OpenAILLM
    llm = OpenAILLM(model="x", base_url="https://api.deepseek.com",
                    api_keys=["k1", "k2", "k3"])
    picked = [llm._pick_client() for _ in range(6)]
    # 6 次轮换 = 每个 key 各 2 次,且只建了 3 个客户端实例
    assert len(set(id(c) for c in picked)) == 3
    assert picked[0] is picked[3] and picked[1] is picked[4]   # 轮换回到同一客户端
