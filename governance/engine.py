"""声明式策略执行器 —— 机制与策略分离。

策略是"数据"(policy.yaml),本类只是"执行器"。这样改规则只动 YAML,
一行 Python 都不用碰;也便于将来让用户自定义策略。

裁决流程(有序,先匹配先生效):
1. 硬边界:命中 forbidden 规则 -> BLOCK(无论如何都拒绝)
2. 主体白名单 / 记忆 scheduler 禁写
3. 命中 confirm 规则(删/改/花钱/控屏) -> ASK
4. 其余 -> ALLOW(读、记记忆、只读 shell、通知等不再弹窗)
"""
from __future__ import annotations

import re
from typing import Any

from core.types import CapabilityCall, Decision, GovReview, Identity, Risk
from governance.classifier import classify

# 内置安全默认:当 policy.yaml 缺失或未安装 PyYAML 时使用,保证开箱即跑。
_DEFAULT_POLICY = {
    "defaults": {"mode": "balanced"},
    "forbidden_patterns": [
        # 递归强制删除:覆盖 -rf / -fr / -r -f / -f -r / --recursive / --force 各种语序
        {"pattern": r"\brm\b[^\n]*\s-[a-z]*r[a-z]*f", "reason": "递归强制删除不可逆,可能误删整个工作区。"},
        {"pattern": r"\brm\b[^\n]*\s-[a-z]*f[a-z]*r", "reason": "递归强制删除不可逆,可能误删整个工作区。"},
        {"pattern": r"\brm\b[^\n]*\s-r\b[^\n]*\s-f\b", "reason": "递归强制删除(分写 -r -f)不可逆。"},
        {"pattern": r"\brm\b[^\n]*\s-f\b[^\n]*\s-r\b", "reason": "递归强制删除(分写 -f -r)不可逆。"},
        {"pattern": r"\brm\b[^\n]*--(recursive|force)", "reason": "递归/强制删除不可逆,可能误删整个工作区。"},
        {"pattern": r":\(\)\s*\{", "reason": "疑似 fork bomb,会耗尽系统资源。"},
        {"pattern": r"force.*push.*\b(main|master)\b", "reason": "强推主干会覆盖他人提交。"},
        {"pattern": r"git\s+push\s+.*--force.*\b(main|master)\b", "reason": "强推主干会覆盖他人提交。"},
        {"pattern": r"mkfs", "reason": "格式化文件系统会清空磁盘数据。"},
        {"pattern": r"dd\s+if=.*of=/dev/", "reason": "直接写裸设备极易造成不可逆损坏。"},
        {"pattern": r">\s*/dev/(sd|nvme|hd|disk)", "reason": "把输出重定向到裸磁盘设备会损坏数据。"},
        {"pattern": r"\bshred\b", "reason": "shred 会不可逆地粉碎文件内容。"},
        {"pattern": r"\bchmod\s+-R\s+0*777\s+/", "reason": "对根目录递归 777 会摧毁系统权限模型。"},
        {"pattern": r"curl[^\n]*\|\s*(sudo\s+)?(ba)?sh\b", "reason": "远程脚本管道直跑等于执行任意代码。"},
        {"pattern": r"wget[^\n]*\|\s*(sudo\s+)?(ba)?sh\b", "reason": "远程脚本管道直跑等于执行任意代码。"},
    ],
    "forbidden_paths": [
        {"pattern": r"\.env", "reason": ".env 含密钥与凭证,读写都可能泄密。"},
        {"pattern": r"credentials", "reason": "凭证文件涉及敏感访问权限。"},
        {"pattern": r"id_rsa", "reason": "SSH 私钥泄露会危及关联主机。"},
        {"pattern": r"\.ssh/", "reason": "SSH 配置目录含私钥与信任主机信息。"},
    ],
    "write_auto_allow_if_granted": True,
    "memory": {
        "block_remember_for_roles": ["scheduler"],
    },
    "confirm": {
        "capabilities": ["fs.write", "gui.control", "payment.",
                         "skill.file_edit", "skill.file_append"],
        "shell_patterns": [
            {"pattern": r"\brm\b", "reason": "删除文件或目录,需确认。"},
            {"pattern": r"\bmv\b", "reason": "移动/重命名会改动现有文件,需确认。"},
            {"pattern": r"\bcp\b", "reason": "复制可能覆盖目标文件(改),需确认。"},
            {"pattern": r"\bchmod\b|\bchown\b", "reason": "修改权限/属主,需确认。"},
            {"pattern": r"\bsed\s+-i", "reason": "原地修改文件内容,需确认。"},
            {"pattern": r">>", "reason": "追加重定向会改动文件,需确认。"},
            {"pattern": r"(?<![=<>])>(?![=])", "reason": "输出重定向会写入/覆盖文件,需确认。"},
            {"pattern": r"\btee\b", "reason": "写入文件,需确认。"},
            {"pattern": r"\btruncate\b", "reason": "截断/清空文件,需确认。"},
            {"pattern": r"\bgit\s+(commit|push|reset|clean|rebase|checkout\s+-f)",
             "reason": "Git 写操作/强改历史,需确认。"},
            {"pattern": r"\b(pip|npm|yarn|pnpm|brew)\s+install",
             "reason": "安装依赖会改动环境,需确认。"},
            {"pattern": r"\bmkdir\b|\btouch\b", "reason": "创建路径/文件(改),需确认。"},
        ],
    },
    "capability_whitelist": {
        "readonly": ["fs.read", "fs.list", "web.search", "web.fetch"],
        "executor": ["fs.read", "fs.list", "fs.write", "shell.run", "web.search", "web.fetch", "skill."],
        "delegate":  ["fs.read", "fs.list", "web.search", "web.fetch"],
        "scheduler": ["fs.read", "fs.list", "memory.recall", "web.search", "web.fetch", "skill."],
    },
    "modes": {
        "conservative": {},
        "balanced": {},
        "aggressive": {},
    },
}


def _compile_rules(raw: list) -> list[tuple]:
    """把规则项编译成 (regex, reason)。兼容两种写法:
    - 字符串:'rm\\s+-rf'        (无 reason,回退通用说明)
    - 字典:  {pattern:..., reason:...}
    """
    out = []
    for item in raw or []:
        if isinstance(item, dict):
            pat = item.get("pattern", "")
            reason = item.get("reason", "")
        else:
            pat, reason = str(item), ""
        if pat:
            out.append((re.compile(pat, re.I), reason))
    return out


class DeclarativePolicy:
    def __init__(
        self,
        registry,
        config_path: str | None = None,
        mode: str | None = None,
    ) -> None:
        self.registry = registry
        self.config = self._load(config_path)
        self._mode_override = mode
        self._forbidden_cmd = _compile_rules(self.config.get("forbidden_patterns", []))
        self._forbidden_path = _compile_rules(self.config.get("forbidden_paths", []))
        self._confirm_shell = _compile_rules(
            (self.config.get("confirm") or {}).get("shell_patterns", [])
            or _DEFAULT_POLICY["confirm"]["shell_patterns"]
        )

    def _active_mode(self) -> str:
        return (
            self._mode_override
            or self.config.get("defaults", {}).get("mode")
            or "balanced"
        )

    def _mode_cfg(self) -> dict:
        modes = self.config.get("modes") or _DEFAULT_POLICY.get("modes", {})
        return dict(modes.get(self._active_mode(), modes.get("balanced", {})))

    @staticmethod
    def _load(config_path: str | None) -> dict:
        if not config_path:
            return dict(_DEFAULT_POLICY)
        try:
            import yaml  # 懒加载;未安装则回退默认
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            # 与默认合并,缺项用默认补齐。
            merged = dict(_DEFAULT_POLICY)
            merged.update(data)
            return merged
        except Exception:
            return dict(_DEFAULT_POLICY)

    def _whitelist_allows(self, call: CapabilityCall, actor: Identity) -> bool | None:
        """按 actor.roles 检查白名单。返回 True=允许, False=拒绝, None=不受限。"""
        whitelist: dict = self.config.get("capability_whitelist", {})
        if not whitelist or not actor.roles:
            return None
        for role in actor.roles:
            allowed = whitelist.get(role)
            if allowed is None:
                continue          # 该角色没有配置 -> 不受此规则限制
            if any(call.name.startswith(prefix) for prefix in allowed):
                return True       # 至少一个角色允许 -> 放行
        # 有角色配置但都没命中 -> 拒绝
        return False

    def review(self, call: CapabilityCall, actor: Identity, ctx: Any) -> Decision:
        """向后兼容入口:只返回裁决。需要 reason/rule 时用 review_detailed。"""
        return self.review_detailed(call, actor, ctx).decision

    def review_detailed(self, call: CapabilityCall, actor: Identity, ctx: Any) -> GovReview:
        """完整裁决:返回 决定 + 原因 + 命中规则,供回传用户与落 trace 统计。"""
        # 0) 按主体鉴权:actor.roles 白名单(多 agent / 多用户安全基础)
        wl = self._whitelist_allows(call, actor)
        if wl is False:
            return GovReview(Decision.BLOCK,
                             reason=f"主体角色 {list(actor.roles)} 无权调用 {call.name}。",
                             rule="whitelist")

        # 1.5) 记忆:仅禁止无人值守主体写入;其余自动记住,不再弹窗
        if call.name == "memory.remember":
            mem_review = self._review_memory(call, actor)
            if mem_review is not None:
                return mem_review

        # 2) 硬边界:命令文本 / 路径命中禁止模式 -> 直接拒绝
        blob = " ".join(str(v) for v in call.args.values())
        for regex, reason in self._forbidden_cmd:
            if regex.search(blob):
                return GovReview(Decision.BLOCK,
                                 reason=reason or "命中命令硬边界,已拒绝。",
                                 rule=f"forbidden_cmd:{regex.pattern}")
        # 敏感路径硬边界:既查显式 path 参数,也查 shell 命令文本——
        # 否则 `shell.run "cat .env"` 这类会从 command 参数绕过路径保护。
        path_surfaces = [str(call.args.get("path", ""))]
        if call.name == "shell.run":
            path_surfaces.append(str(call.args.get("command", "")))
        for surface in path_surfaces:
            if not surface:
                continue
            for regex, reason in self._forbidden_path:
                if regex.search(surface):
                    return GovReview(Decision.BLOCK,
                                     reason=reason or "命中敏感路径硬边界,已拒绝。",
                                     rule=f"forbidden_path:{regex.pattern}")

        # 2.5) 本任务已点过「允许」→ 不再重复询问(一次弹窗管一整轮)
        if getattr(ctx, "task_auto_approve", False):
            return GovReview(
                Decision.ALLOW,
                reason="本任务已授权,后续同类操作自动放行。",
                rule="task:auto",
            )
        if self._capability_granted(call, ctx):
            return GovReview(
                Decision.ALLOW,
                reason="该能力本会话已授权放手。",
                rule="grant:capability",
            )

        # 3) 仅删/改/花钱/控屏需确认;路径已授权则写文件也可放行
        risk = classify(call, self.registry)
        if risk == Risk.FORBIDDEN:
            return GovReview(Decision.BLOCK, reason="该能力被标记为禁止。", rule="risk:forbidden")

        need, reason, rule = self._needs_confirm(call)
        # 风险兜底:任何 DESTRUCTIVE 能力(MCP 外部工具 / 未来新增工具等)默认需确认,
        # 不能因为不在 confirm 名单里就自动放行。shell.run 有自己的命令级判定,排除在外。
        if not need and call.name != "shell.run" and risk >= Risk.DESTRUCTIVE:
            need = True
            reason = "高危能力(可能不可逆或有外部副作用),需你确认。"
            rule = "risk:destructive"
        if need:
            if (
                call.name == "fs.write"
                and self.config.get("write_auto_allow_if_granted", True)
                and self._granted(call, ctx)
            ):
                return GovReview(
                    Decision.ALLOW,
                    reason="写操作,但该路径本会话已授权放手。",
                    rule="grant",
                )
            return GovReview(Decision.ASK, reason=reason, rule=rule)

        return GovReview(Decision.ALLOW, reason="无需确认,自动放行。", rule="auto")

    def _needs_confirm(self, call: CapabilityCall) -> tuple[bool, str, str]:
        """仅删/改/花钱/控屏返回 True。shell.run 按命令内容细分。"""
        confirm_cfg = self.config.get("confirm") or _DEFAULT_POLICY.get("confirm") or {}
        caps = confirm_cfg.get("capabilities") or ["fs.write", "gui.control", "payment."]
        for prefix in caps:
            if call.name == prefix or call.name.startswith(prefix):
                if call.name == "fs.write":
                    return True, "写文件会改动磁盘内容,需你确认。", "confirm:fs.write"
                if call.name.startswith("gui."):
                    return True, "控制电脑图形界面,需你确认。", "confirm:gui"
                if call.name.startswith("payment."):
                    return True, "涉及花钱/支付,需你确认。", "confirm:payment"
                return True, "该操作会改动系统或产生费用,需你确认。", f"confirm:{call.name}"

        if call.name == "shell.run":
            cmd = str(call.args.get("command", "")).strip()
            if not cmd:
                return False, "", ""
            for regex, reason in self._confirm_shell:
                if regex.search(cmd):
                    return (
                        True,
                        reason or "命令可能删除或修改文件,需你确认。",
                        f"confirm:shell:{regex.pattern}",
                    )
        return False, "", ""

    def _review_memory(self, call: CapabilityCall, actor: Identity) -> GovReview | None:
        """memory.remember:scheduler 禁止;其余自动放行。"""
        mem_cfg = self.config.get("memory") or {}
        block_roles = mem_cfg.get("block_remember_for_roles") or ["scheduler"]
        if actor.roles and any(r in block_roles for r in actor.roles):
            return GovReview(
                Decision.BLOCK,
                reason="无人值守主体(如定时任务)不允许写入长期记忆,避免错误记忆持久污染。",
                rule="memory:block_unattended",
            )
        return GovReview(Decision.ALLOW, reason="记住偏好/事实,自动放行。", rule="memory:auto")

    @staticmethod
    def _granted(call: CapabilityCall, ctx: Any) -> bool:
        """用户是否已对该路径/目录临时授权(本会话内、有作用域的最小授权)。"""
        grant_fn = getattr(ctx, "is_granted", None)
        if grant_fn is None:
            return False
        return bool(grant_fn(call.args.get("path", "")))

    @staticmethod
    def _capability_granted(call: CapabilityCall, ctx: Any) -> bool:
        grant_fn = getattr(ctx, "is_capability_granted", None)
        if grant_fn is None:
            return False
        return bool(grant_fn(call.name))
