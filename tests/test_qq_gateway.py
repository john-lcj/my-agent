"""QQ 官方机器人 · WS 网关状态机回归 —— 不连真实网关,纯帧处理断言。"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from channels.qq_channel import (
    QQChannel, _DEFAULT_INTENTS, _OP_HELLO, _OP_DISPATCH,
    _OP_HEARTBEAT_ACK, _OP_RECONNECT, _OP_INVALID_SESSION,
)


def _ch():
    return QQChannel(app_id="123", app_secret="sec")


def _drain(ch):
    try:
        return ch._inbox.get_nowait()
    except asyncio.QueueEmpty:
        return None


def test_identify_frame_shape():
    ch = _ch()
    idf = ch._build_identify("ACCESS")
    assert idf["op"] == 2
    assert idf["d"]["token"] == "QQBot ACCESS"
    assert idf["d"]["intents"] == _DEFAULT_INTENTS
    assert idf["d"]["shard"] == [0, 1]


def test_intents_env_override(monkeypatch=None):
    os.environ["QQ_BOT_INTENTS"] = "512"
    try:
        assert _ch()._intents() == 512
    finally:
        del os.environ["QQ_BOT_INTENTS"]


def test_hello_returns_interval():
    ch = _ch()
    tag, payload = asyncio.run(ch._on_gateway_frame(
        {"op": _OP_HELLO, "d": {"heartbeat_interval": 41250}}))
    assert tag == "hello" and payload == 41250


def test_dispatch_enqueues_message_and_tracks_seq():
    ch = _ch()
    frame = {
        "op": _OP_DISPATCH, "s": 7, "t": "GROUP_AT_MESSAGE_CREATE",
        "d": {"content": "查下天气", "author": {"id": "u1"},
              "group_openid": "g1", "id": "m1"},
    }
    tag, t = asyncio.run(ch._on_gateway_frame(frame))
    assert tag == "dispatch" and t == "GROUP_AT_MESSAGE_CREATE"
    assert ch._gw_seq == 7
    item = _drain(ch)
    assert item is not None
    msg_ctx, text = item
    assert text == "查下天气" and msg_ctx["group_openid"] == "g1"


def test_ready_does_not_enqueue():
    ch = _ch()
    tag, _ = asyncio.run(ch._on_gateway_frame(
        {"op": _OP_DISPATCH, "s": 1, "t": "READY", "d": {"session_id": "x"}}))
    assert tag == "ready"
    assert _drain(ch) is None


def test_ack_and_reconnect_tags():
    ch = _ch()
    assert asyncio.run(ch._on_gateway_frame({"op": _OP_HEARTBEAT_ACK}))[0] == "ack"
    assert asyncio.run(ch._on_gateway_frame({"op": _OP_RECONNECT}))[0] == "reconnect"
    assert asyncio.run(ch._on_gateway_frame({"op": _OP_INVALID_SESSION}))[0] == "reconnect"


def test_confirm_reply_via_dispatch():
    ch = _ch()

    async def scenario():
        from core.types import CapabilityCall, Decision
        ch._current_ctx = {"group_openid": "g1", "msg_id": "m1"}
        sent = []

        async def fake_reply(text):
            sent.append(text)
        ch._reply = fake_reply
        task = asyncio.create_task(ch.confirm(CapabilityCall(name="fs.write", args={}), Decision.ASK, "写"))
        await asyncio.sleep(0.01)
        import re
        cid = re.search(r"y ([A-F0-9]{6})", sent[0]).group(1)
        # 模拟用户在群里回复 "y 确认码"
        await ch._on_gateway_frame({
            "op": _OP_DISPATCH, "s": 2, "t": "GROUP_AT_MESSAGE_CREATE",
            "d": {"content": f"y {cid}", "author": {"id": "u1"}, "group_openid": "g1", "id": "m2"},
        })
        return await asyncio.wait_for(task, timeout=1)

    assert asyncio.run(scenario()) is True
