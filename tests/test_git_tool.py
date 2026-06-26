"""git.read / git.commit 能力 —— 在临时真实 git 仓库里验证安全行为。"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities.tools.git_tool import GitRead, GitCommit
from core.types import Risk


def _init_repo(tmp_path):
    d = str(tmp_path)
    subprocess.run(["git", "init", "-q", d], check=True)
    subprocess.run(["git", "-C", d, "config", "user.email", "t@t.co"], check=True)
    subprocess.run(["git", "-C", d, "config", "user.name", "t"], check=True)
    return d


def test_risk_levels():
    assert GitRead.risk == Risk.READ      # 只读永不打扰
    assert GitCommit.risk == Risk.WRITE   # 提交默认询问


def test_read_status_and_log(tmp_path, monkeypatch):
    d = _init_repo(tmp_path)
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", d)
    (tmp_path / "a.txt").write_text("hi")
    r = asyncio.run(GitRead().invoke({"op": "status"}, None))
    assert r.ok and "a.txt" in r.output           # 未跟踪文件出现在 status
    bad = asyncio.run(GitRead().invoke({"op": "rm -rf"}, None))
    assert not bad.ok and "不支持" in bad.error    # 非白名单子命令被拒


def test_commit_then_log(tmp_path, monkeypatch):
    d = _init_repo(tmp_path)
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", d)
    (tmp_path / "a.txt").write_text("hi")
    r = asyncio.run(GitCommit().invoke({"message": "首次提交"}, None))
    assert r.ok and "已提交" in r.output and "push 请你自己执行" in r.output
    lg = asyncio.run(GitRead().invoke({"op": "log"}, None))
    assert "首次提交" in lg.output


def test_commit_blocks_secrets(tmp_path, monkeypatch):
    d = _init_repo(tmp_path)
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", d)
    (tmp_path / ".env").write_text("SECRET=abc")
    (tmp_path / "ok.txt").write_text("fine")
    r = asyncio.run(GitCommit().invoke({"message": "试图提交"}, None))
    assert not r.ok and ".env" in r.error          # 敏感文件被挡
    # 撤销暂存后应仍可正常提交非敏感文件
    r2 = asyncio.run(GitCommit().invoke({"message": "只提交 ok", "paths": ["ok.txt"]}, None))
    assert r2.ok


def test_commit_empty_tree(tmp_path, monkeypatch):
    d = _init_repo(tmp_path)
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", d)
    r = asyncio.run(GitCommit().invoke({"message": "空"}, None))
    assert not r.ok and "干净" in r.error


def test_repo_dir_confined_to_workspace(tmp_path, monkeypatch):
    d = _init_repo(tmp_path)
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", d)
    r = asyncio.run(GitRead().invoke({"op": "status", "path": "../../etc"}, None))
    assert not r.ok and "越出工作区" in r.error
