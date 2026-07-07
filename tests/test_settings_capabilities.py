"""agent 自管设置能力:白名单、API Key、定时任务扩展。"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.types import CapabilityCall, Decision, Identity


def test_channel_allowlist_roundtrip():
    import capabilities.tools.channel as ch
    d = tempfile.mkdtemp()
    path = os.path.join(d, "channels.json")
    os.environ["AGENT_LOG_DIR"] = d
    ch._STORE = None
    from channels.config_store import ChannelConfigStore
    ch._STORE = ChannelConfigStore(path=path)
    ch._STORE.update("email", {"user": "me@qq.com", "password": "x"})

    configure = ch.ChannelConfigure()
    status = ch.ChannelStatus()
    r = asyncio.run(configure.invoke(
        {"allowed": "boss@outlook.com, me@qq.com"}, None))
    assert r.ok, r.error
    assert "boss@outlook.com" in os.environ["EMAIL_ALLOWED_SENDERS"]
    assert "boss@outlook.com" in os.environ["EMAIL_ALLOWED_RECIPIENTS"]

    s = asyncio.run(status.invoke({}, None))
    assert s.ok and "boss@outlook.com" in s.output


def test_model_key_save_list_clear():
    import capabilities.tools.model_key as mk
    d = tempfile.mkdtemp()
    path = os.path.join(d, "model_keys.json")
    os.environ["AGENT_LOG_DIR"] = d
    mk._STORE = None
    from server.model_keys import ModelKeyStore
    mk._STORE = ModelKeyStore(path=path)

    save, lst, clear = mk.ModelKeySave(), mk.ModelKeyList(), mk.ModelKeyClear()
    r = asyncio.run(save.invoke({"provider": "deepseek", "key": "sk-test-key-123"}, None))
    assert r.ok
    out = asyncio.run(lst.invoke({}, None))
    assert "deepseek" in out.output
    assert "sk-test" not in out.output
    c = asyncio.run(clear.invoke({"provider": "deepseek"}, None))
    assert c.ok


def test_schedule_update_and_run():
    import capabilities.tools.schedule as sched
    d = tempfile.mkdtemp()
    sched._STORE = None
    from scheduler.store import TaskStore
    sched._STORE = TaskStore(db_path=os.path.join(d, "tasks.db"))

    create = sched.ScheduleCreate()
    update = sched.ScheduleUpdate()
    run = sched.ScheduleRun()
    r = asyncio.run(create.invoke(
        {"name": "t", "prompt": "p", "schedule_type": "daily", "at_hhmm": "09:00"}, None))
    assert r.ok
    tid = sched._STORE.list()[0].id

    u = asyncio.run(update.invoke({"id": tid, "enabled": False, "prompt": "new prompt"}, None))
    assert u.ok
    task = sched._STORE.get(tid)
    assert task.enabled is False
    assert task.prompt == "new prompt"

    rn = asyncio.run(run.invoke({"id": tid}, None))
    assert rn.ok
    assert sched._STORE.get(tid).next_run == 0.0


def _policy(*tools):
    from capabilities.base import CapabilityRegistry
    from governance.engine import DeclarativePolicy
    return DeclarativePolicy(CapabilityRegistry(list(tools)), config_path="governance/policy.yaml")


class _Ctx:
    def __init__(self, coworker): self.coworker = coworker


def test_new_settings_confirm_gates():
    from capabilities.tools.channel import ChannelConfigure
    from capabilities.tools.model_key import ModelKeySave, ModelKeyClear
    from capabilities.tools.schedule import ScheduleUpdate, ScheduleRun
    os.environ.pop("AGENT_WORKSPACE_ROOT", None)
    pol = _policy(ChannelConfigure(), ModelKeySave(), ModelKeyClear(), ScheduleUpdate(), ScheduleRun())
    for name, args in [
        ("channel.configure", {"allowed": "a@x.com"}),
        ("model_key.save", {"provider": "deepseek", "key": "sk-x"}),
        ("model_key.clear", {"provider": "deepseek"}),
        ("schedule.update", {"id": "abc", "enabled": True}),
        ("schedule.run", {"id": "abc"}),
    ]:
        c = CapabilityCall(name=name, args=args)
        assert pol.review(c, Identity(), _Ctx(False)) == Decision.ASK
        assert pol.review(c, Identity(), _Ctx(True)) == Decision.ALLOW
