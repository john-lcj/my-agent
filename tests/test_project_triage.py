"""复杂任务提前派:looks_like_project 启发式回归(保守:不误判简单任务)。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.coordinator import looks_like_project


def test_chat_and_simple_stay_captain():
    for t in ["你好", "你是谁", "解释一下什么是 RAG", "帮我查一下今天天气", "谢谢"]:
        assert looks_like_project(t) is False, t


def test_obvious_projects_dispatch():
    cases = [
        "先调研主流自建梯子方案,再写成部署脚本放到 logs/reports",
        "帮我搭建一个个人 VPN,生成服务器安装脚本和客户端配置",
        "统计项目代码规模,然后整理成报告并生成一个网页展示",
        "批量抓取这些网址的标题,汇总成表格",
    ]
    for t in cases:
        assert looks_like_project(t) is True, t


def test_numbered_steps_dispatch():
    t = "帮我做几件事\n1. 读 README\n2. 提炼卖点\n3. 写成 highlights.md"
    assert looks_like_project(t) is True


def test_single_short_action_stays_captain():
    # 单步、短:交给 Captain 自己快速完成,别空派
    assert looks_like_project("读一下 config.py") is False
    assert looks_like_project("把这句话翻译成英文") is False
