"""policy.yaml 热重载 —— 改规则后无需重启 server。"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities.base import CapabilityRegistry
from capabilities.tools.fs import WriteFile
from core.types import CapabilityCall, Decision, Identity
from governance.engine import DeclarativePolicy


def test_policy_hot_reload_picks_up_whitelist(tmp_path):
    import yaml

    cfg = tmp_path / "policy.yaml"
    cfg.write_text(
        yaml.dump({
            "capability_whitelist": {
                "researcher": ["fs.read", "fs.list"],
            },
        }),
        encoding="utf-8",
    )
    reg = CapabilityRegistry([WriteFile()])
    pol = DeclarativePolicy(reg, str(cfg))
    actor = Identity(roles=("researcher",))
    call = CapabilityCall(name="fs.write", args={"path": "x.md", "content": "t"})

    assert pol.review_detailed(call, actor, None).decision == Decision.BLOCK

    time.sleep(0.01)
    cfg.write_text(
        yaml.dump({
            "capability_whitelist": {
                "researcher": ["fs.read", "fs.list", "fs.write"],
            },
        }),
        encoding="utf-8",
    )
    os.utime(cfg, (time.time() + 1, time.time() + 1))

    assert pol.review_detailed(call, actor, None).decision != Decision.BLOCK
