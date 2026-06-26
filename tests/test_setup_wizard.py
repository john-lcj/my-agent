"""配置向导 —— 用临时 .env + 模拟输入,验证写入正确、不碰真实 .env。"""
from __future__ import annotations

import importlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))


def _run_with_inputs(tmp_env, answers, monkeypatch):
    monkeypatch.setenv("AGENT_ENV_FILE", str(tmp_env))
    import setup_wizard
    importlib.reload(setup_wizard)   # 让它重新读 AGENT_ENV_FILE
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(it))
    rc = setup_wizard.main()
    return rc, dict(
        ln.split("=", 1) for ln in open(tmp_env, encoding="utf-8").read().splitlines()
        if "=" in ln and not ln.lstrip().startswith("#"))


def test_wizard_writes_deepseek_zhipu_token(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    answers = [
        "1", "sk-deepseek-xxx", "",     # 主模型: deepseek, key, 默认模型id
        "1", "zk-image-yyy",            # 文生图: 智谱, image key
        "1",                            # 搜索: 跳过
        "2",                            # 预设: 职场办公(office)
        "2", "1",                       # 令牌: 生成新的; 绑定本机
        "y",                            # 确认写入
    ]
    rc, kv = _run_with_inputs(env, answers, monkeypatch)
    assert rc == 0
    assert kv["DEEPSEEK_API_KEY"] == "sk-deepseek-xxx"
    assert kv["AGENT_MODEL"] == "deepseek-v4-flash"
    assert kv["IMAGE_PROVIDER"] == "zhipu" and kv["IMAGE_API_KEY"] == "zk-image-yyy"
    assert kv["AGENT_PERSONA_PRESET"] == "office"
    assert kv["AGENT_WEB_HOST"] == "127.0.0.1"
    assert len(kv["AGENT_API_TOKEN"]) >= 20          # 真生成了令牌
    assert oct(os.stat(env).st_mode)[-3:] == "600"   # 权限收紧


def test_wizard_preserves_existing_and_backs_up(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("DEEPSEEK_API_KEY=keep-me\n# 注释保留\nFOO=bar\n", encoding="utf-8")
    answers = [
        "4",            # 主模型: 跳过保持当前
        "3",            # 文生图: 跳过
        "1",            # 搜索: 跳过
        "1",            # 预设: 通用
        "1", "1",       # 令牌: 保持当前; 绑定本机
        "y",
    ]
    rc, kv = _run_with_inputs(env, answers, monkeypatch)
    assert rc == 0
    assert kv["DEEPSEEK_API_KEY"] == "keep-me"        # 原值没被动
    assert kv["FOO"] == "bar"                          # 无关键保留
    assert "# 注释保留" in open(env, encoding="utf-8").read()
    assert (tmp_path / ".env.bak").is_file()           # 写前备份
