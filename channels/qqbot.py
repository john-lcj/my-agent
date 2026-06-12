"""QQ 机器人(qqbot) —— Agent 内置渠道入口。

实现见 `channels.qq_channel.QQChannel`;本模块提供统一别名与状态查询。
"""
from __future__ import annotations

from channels.qq_channel import QQChannel, QQChannel as QQBotChannel, qq_channel_info, print_qq_status

__all__ = ["QQChannel", "QQBotChannel", "qq_channel_info", "print_qq_status"]
