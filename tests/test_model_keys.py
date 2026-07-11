"""模型接入存储 + 连通性测试 回归(离线:不发真实网络)。"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.model_keys import ModelKeyStore, PROVIDER_PRESETS, migrate_mimo_model
from server.model_test import friendly_error_message
from server.model_test import test_endpoint as _test_endpoint  # 别名:避免 pytest 误收集


def _store(tmp_path):
    return ModelKeyStore(path=str(tmp_path / "mk.json"))


def test_presets_listed_with_three_states(tmp_path, monkeypatch):
    for m in PROVIDER_PRESETS.values():
        monkeypatch.delenv(m["key_env"], raising=False)
    s = _store(tmp_path)
    masked = s.get_masked()
    assert "deepseek" in masked and "xiaomi_vision" in masked and "image" in masked
    assert masked["deepseek"]["configured"] is False
    assert masked["deepseek"]["verified"] is False
    # 默认 base_url/model 透出,方便前端预填
    assert masked["deepseek"]["base_url"] == "https://api.deepseek.com"


def test_save_key_base_url_model_and_env(tmp_path, monkeypatch):
    monkeypatch.delenv("VISION_API_KEY", raising=False)
    s = _store(tmp_path)
    s.update("xiaomi_vision", key="sk-xyz", base_url="https://api.xiaomimimo.com/v1", model="mimo-v2-omni")
    m = s.get_masked()["xiaomi_vision"]
    assert m["configured"] is True and m["key"] == "******"   # 不回明文
    assert m["model"] == "mimo-v2.5-pro"  # V2 自动映射
    assert os.environ["VISION_API_KEY"] == "sk-xyz"
    assert os.environ["VISION_MODEL"] == "mimo-v2.5-pro"


def test_xiaomi_default_model_v25(tmp_path):
    s = _store(tmp_path)
    assert s.get_masked()["xiaomi_vision"]["default_model"] == "mimo-v2.5-pro"


def test_mainstream_endpoint_preset_stored(tmp_path):
    s = _store(tmp_path)
    s.update("kimi", key="sk-k", base_url="https://api.moonshot.cn/v1", model="moonshot-v1-8k", label="Kimi")
    m = s.get_masked()["kimi"]
    assert m["builtin"] is True and m["label"] == "Kimi / Moonshot" and m["configured"] is True


def test_custom_endpoint_stored(tmp_path):
    s = _store(tmp_path)
    s.update("custom_vendor", key="sk-c", base_url="https://api.example.com/v1", model="custom-chat", label="Custom")
    m = s.get_masked()["custom_vendor"]
    assert m["builtin"] is False and m["label"] == "Custom" and m["configured"] is True


def test_backward_compat_old_string_format(tmp_path):
    import json
    p = tmp_path / "mk.json"
    p.write_text(json.dumps({"deepseek": "sk-old"}), encoding="utf-8")
    s = ModelKeyStore(path=str(p))
    assert s.get_masked()["deepseek"]["configured"] is True
    assert os.environ["DEEPSEEK_API_KEY"] == "sk-old"


def test_placeholder_key_is_not_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-xxx")
    s = _store(tmp_path)
    assert s.get_masked()["deepseek"]["configured"] is False
    assert s.get_config("deepseek")["key"] == ""
    s.update("deepseek", key="sk-deepseek-xxx")
    assert s.get_masked()["deepseek"]["configured"] is False


def test_verified_state(tmp_path):
    s = _store(tmp_path)
    s.update("deepseek", key="sk-x")
    assert s.get_masked()["deepseek"]["verified"] is False
    s.mark_verified("deepseek", True)
    assert s.get_masked()["deepseek"]["verified"] is True
    # 换 key 后验证状态作废
    s.update("deepseek", key="sk-new")
    assert s.get_masked()["deepseek"]["verified"] is False


def test_verified_state_can_be_recorded_for_env_only_key(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-from-env")
    s = _store(tmp_path)
    s.mark_verified("deepseek", True)
    state = s.get_masked()["deepseek"]
    assert state["configured"] is True
    assert state["verified"] is True


def test_endpoint_or_model_change_invalidates_verification(tmp_path):
    s = _store(tmp_path)
    s.update("custom", key="sk-x", base_url="https://one.example/v1", model="model-a")
    s.mark_verified("custom", True)
    s.update("custom", base_url="https://two.example/v1")
    assert s.get_masked()["custom"]["verified"] is False
    s.mark_verified("custom", True)
    s.update("custom", model="model-b")
    assert s.get_masked()["custom"]["verified"] is False


def test_migrate_mimo_model():
    assert migrate_mimo_model("mimo-v2-omni") == "mimo-v2.5-pro"
    assert migrate_mimo_model("mimo-v2.5-pro") == "mimo-v2.5-pro"
    assert migrate_mimo_model("gpt-4o") == "gpt-4o"


def test_test_endpoint_no_key_is_clear_error():
    r = asyncio.run(_test_endpoint("openai", "chat", "", "", "gpt-4o"))
    assert not r["ok"] and "Key" in r["error"]


def test_test_endpoint_no_model():
    r = asyncio.run(_test_endpoint("openai", "chat", "", "sk-x", ""))
    assert not r["ok"] and "模型" in r["error"]


def test_model_error_insufficient_credits_is_friendly():
    msg = friendly_error_message("Error code: 402 - Insufficient credits. This account never purchased credits.")
    assert "账号余额不足" in msg
    assert "充值" in msg
