"""Git 能力(面向程序员)—— 受治理的安全 git 操作。

设计原则(安全第一):
  · git.read  (READ,永不打扰):status/diff/log/show/branch/blame/remote/stash 等只读子命令;
  · git.commit(WRITE,默认询问):只做 `add` + `commit`,绝不 push;提交前挡住 .env 等敏感文件。
  · push / reset --hard / clean -fd / rebase / force 等危险操作**故意不提供**——
    agent 只能把命令告诉主人、由主人亲自执行。这比"自动 push 错东西"安全得多。

实现用 argv 列表(非 shell 字符串),从根上杜绝命令注入;操作目录限定在工作区内。
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

from capabilities.tools.base import Tool
from core.types import CapabilityResult, Risk
from governance.workspace import resolve_path, workspace_root

# 只读子命令白名单 → 安全 argv 模板(N/target 由参数填)
_READ_OPS = {
    "status": ["status", "--short", "--branch"],
    "log":    ["log", "--oneline", "--decorate", "-n", "{n}"],
    "diff":   ["diff"],            # 可附 target(文件或 --staged)
    "show":   ["show", "--stat"],  # 需 target(ref)
    "branch": ["branch", "-vv"],
    "remote": ["remote", "-v"],
    "blame":  ["blame"],           # 需 target(文件)
    "stash":  ["stash", "list"],
    "tag":    ["tag", "-l"],
}
# 提交前绝不允许进入暂存区的敏感文件(防把密钥提交上去)
_SECRET_HINTS = (".env", "model_keys.json", "channels.json", "vault.db", "secrets")
_MAX_OUT = 12000


def _repo_dir(args: dict) -> tuple[str, str]:
    """解析仓库目录:参数 path 优先,否则工作区根;必须在工作区内且是 git 仓库。"""
    ws = workspace_root()
    p = str(args.get("path", "")).strip()
    d, error = resolve_path(p, default=".", require_exists=True)
    if error:
        return "", "目录越出工作区" if "outside" in error else error
    if not os.path.isdir(d):
        return "", f"不是有效目录:{d}"
    if not os.path.isdir(os.path.join(d, ".git")):
        # 也可能在子目录;用 rev-parse 兜底由调用方处理。这里先粗判。
        if not os.path.isdir(os.path.join(ws, ".git")):
            return "", f"不是 git 仓库(没找到 .git):{d}"
    return d, ""


async def _run_git(cwd: str, argv: list[str]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *argv, cwd=cwd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=30)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "", "git 执行超时"
    return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


class GitRead(Tool):
    name = "git.read"
    risk = Risk.READ
    description = ("只读查看 git 仓库状态:status(改动)/log(历史)/diff(差异)/show/branch/"
                  "remote/blame/stash/tag。永不改动仓库,适合'看看改了啥、最近提交、某文件历史'。")
    schema = {
        "type": "object",
        "properties": {
            "op": {"type": "string",
                   "description": "status|log|diff|show|branch|remote|blame|stash|tag"},
            "target": {"type": "string",
                       "description": "可选:文件路径或 ref(diff 可传 --staged;show/blame 需 ref/文件)"},
            "n": {"type": "integer", "description": "log 条数,默认 20"},
            "path": {"type": "string", "description": "仓库目录(默认工作区根)"},
        },
        "required": ["op"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        op = str(args.get("op", "")).strip().lower()
        if op not in _READ_OPS:
            return CapabilityResult(ok=False, error=f"不支持的只读操作:{op};可用:{', '.join(_READ_OPS)}")
        cwd, err = _repo_dir(args)
        if err:
            return CapabilityResult(ok=False, error=err)
        argv = [seg.format(n=int(args.get("n", 20) or 20)) for seg in _READ_OPS[op]]
        target = str(args.get("target", "")).strip()
        if target:
            # 安全:只允许 --staged/--cached 这两个旗标,其余以 '-' 开头一律拒(防注入怪旗标)
            if target.startswith("-") and target not in ("--staged", "--cached"):
                return CapabilityResult(ok=False, error=f"不允许的参数:{target}")
            if ".." in target.split("/"):
                return CapabilityResult(ok=False, error="target 不允许路径穿越")
            argv.append(target)
        code, out, errtxt = await _run_git(cwd, argv)
        if code != 0:
            return CapabilityResult(ok=False, error=(errtxt or out or f"git 退出码 {code}").strip()[:_MAX_OUT])
        body = (out or "(无输出/工作区干净)").strip()
        return CapabilityResult(ok=True, output=body[:_MAX_OUT])


class GitCommit(Tool):
    name = "git.commit"
    risk = Risk.WRITE   # 默认询问;仅显式授权后才可免确认。
    description = ("把改动提交到本地 git 仓库:暂存(add)+ 提交(commit -m)。"
                  "只提交到本地,**绝不 push**;提交前自动挡住 .env 等敏感文件。"
                  "push/回滚/重置请让主人自己执行。")
    schema = {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "提交信息(必填,简明说明改了什么)"},
            "paths": {"type": "array", "items": {"type": "string"},
                      "description": "要提交的文件(可选;不填=暂存全部改动)"},
            "path": {"type": "string", "description": "仓库目录(默认工作区根)"},
        },
        "required": ["message"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        msg = str(args.get("message", "")).strip()
        if not msg:
            return CapabilityResult(ok=False, error="缺少提交信息 message")
        cwd, err = _repo_dir(args)
        if err:
            return CapabilityResult(ok=False, error=err)
        paths = args.get("paths") or []
        if paths and not isinstance(paths, list):
            return CapabilityResult(ok=False, error="paths 必须是数组")

        # 暂存:指定文件或全部
        if paths:
            for p in paths:
                if str(p).startswith("-"):
                    return CapabilityResult(ok=False, error=f"非法路径:{p}")
            code, _o, e = await _run_git(cwd, ["add", "--", *map(str, paths)])
        else:
            code, _o, e = await _run_git(cwd, ["add", "-A"])
        if code != 0:
            return CapabilityResult(ok=False, error=f"git add 失败:{e.strip()}")

        # 安全闸:暂存区里若有敏感文件,拒绝提交
        _c, staged, _e = await _run_git(cwd, ["diff", "--cached", "--name-only"])
        leaked = [ln for ln in staged.splitlines()
                  if any(h in ln for h in _SECRET_HINTS)]
        if leaked:
            await _run_git(cwd, ["reset", "-q"])   # 撤销暂存,恢复原状
            return CapabilityResult(
                ok=False,
                error=("检测到敏感文件被暂存,已撤销暂存、拒绝提交:"
                       + "、".join(leaked[:5]) + "。请确认它们已在 .gitignore 中。"))
        if not staged.strip():
            return CapabilityResult(ok=False, error="没有可提交的改动(工作区干净)。")

        code, out, e = await _run_git(cwd, ["commit", "-m", msg])
        if code != 0:
            return CapabilityResult(ok=False, error=f"git commit 失败:{(e or out).strip()}")
        # 取短哈希回报
        _c, sha, _e = await _run_git(cwd, ["rev-parse", "--short", "HEAD"])
        n = len(staged.strip().splitlines())
        return CapabilityResult(
            ok=True,
            output=f"已提交 {sha.strip()}:{msg}(含 {n} 个文件)。注意:只提交到本地,push 请你自己执行。")
