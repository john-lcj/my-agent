"""QQ(OneBot v11 / NapCat)渠道回归 —— 不连真实 ws,纯解析/路由断言。"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from channels.onebot_channel import OneBotChannel
from core.types import CapabilityCall, Decision, Event, EventType


def _drain(ch):
    """取出 inbox 里已入队的 (ctx, text),空则 None。"""
    try:
        return ch._inbox.get_nowait()
    except asyncio.QueueEmpty:
        return None


def test_private_message_enqueued():
    ch = OneBotChannel(ws_url="ws://x", master_uin="")
    ch._handle_event({
        "post_type": "message", "message_type": "private",
        "user_id": 10001, "raw_message": "你好", "self_id": 999,
    })
    item = _drain(ch)
    assert item is not None
    ctx, text = item
    assert text == "你好"
    assert ctx["message_type"] == "private" and ctx["user_id"] == "10001"


def test_master_filter_blocks_others():
    ch = OneBotChannel(master_uin="10001")
    # 非主人 → 忽略
    ch._handle_event({"post_type": "message", "message_type": "private",
                      "user_id": 20002, "raw_message": "hi", "self_id": 999})
    assert _drain(ch) is None
    # 主人 → 放行
    ch._handle_event({"post_type": "message", "message_type": "private",
                      "user_id": 10001, "raw_message": "hi", "self_id": 999})
    assert _drain(ch) is not None


def test_group_requires_at_self():
    ch = OneBotChannel(master_uin="")
    base = {"post_type": "message", "message_type": "group",
            "group_id": 555, "user_id": 10001, "self_id": 999}
    # 没 @机器人 → 忽略
    ch._handle_event({**base, "raw_message": "大家好"})
    assert _drain(ch) is None
    # @了机器人 → 放行,且文本去掉 CQ 码
    ch._handle_event({**base, "raw_message": "[CQ:at,qq=999] 帮我查天气"})
    item = _drain(ch)
    assert item is not None
    ctx, text = item
    assert text == "帮我查天气"
    assert ctx["message_type"] == "group" and ctx["group_id"] == 555


def test_meta_event_ignored():
    ch = OneBotChannel()
    ch._handle_event({"post_type": "meta_event", "meta_event_type": "heartbeat"})
    assert _drain(ch) is None


def test_build_send_action_routing():
    ch = OneBotChannel()
    priv = ch._build_send_action({"message_type": "private", "user_id": "10001"}, "嗨")
    assert priv["action"] == "send_msg"
    assert priv["params"]["message_type"] == "private"
    assert priv["params"]["user_id"] == "10001" and priv["params"]["message"] == "嗨"

    grp = ch._build_send_action({"message_type": "group", "group_id": 555}, "在")
    assert grp["params"]["message_type"] == "group" and grp["params"]["group_id"] == 555


def test_confirm_reply_resolves_future():
    ch = OneBotChannel(master_uin="10001")

    async def scenario():
        call = CapabilityCall(name="fs.write", args={"path": "x"})
        ch._current_ctx = {"message_type": "private", "user_id": "10001"}
        sent = []
        ch._send_action = lambda action: sent.append(action) or _noop()
        task = asyncio.create_task(ch.confirm(call, Decision.ASK, "写文件"))
        await asyncio.sleep(0.01)
        # 提取确认码(发出去的提示里有 6 位码)
        prompt = sent[0]["params"]["message"]
        import re
        cid = re.search(r"y ([A-F0-9]{6})", prompt).group(1)
        # 主人回复 y 确认码
        ch._handle_event({"post_type": "message", "message_type": "private",
                          "user_id": 10001, "raw_message": f"y {cid}", "self_id": 999})
        return await asyncio.wait_for(task, timeout=1)

    assert asyncio.run(scenario()) is True


async def _noop():
    return None


def test_emit_sends_reply():
    ch = OneBotChannel()
    sent = []
    ch._send_action = lambda action: sent.append(action) or _noop()

    async def scenario():
        ch._current_ctx = {"message_type": "private", "user_id": "10001"}
        ch.emit(Event(type=EventType.ASSISTANT_MESSAGE, payload={"text": "结果好了"}))
        await asyncio.sleep(0.01)

    asyncio.run(scenario())
    assert sent and sent[0]["params"]["message"] == "结果好了"
