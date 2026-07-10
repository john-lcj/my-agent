"""Minimal subprocess entrypoint for an untrusted workspace skill."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys


def main() -> int:
    impl_path = sys.argv[1] if len(sys.argv) == 2 else ""
    if not impl_path:
        return 2
    try:
        args = json.loads(sys.stdin.read() or "{}")
        spec = importlib.util.spec_from_file_location("sandboxed_workspace_skill", impl_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        result = asyncio.run(module.run(args if isinstance(args, dict) else {}, None))
        payload = {"ok": bool(result.ok), "output": str(result.output or ""), "error": result.error}
    except Exception as exc:
        payload = {"ok": False, "output": "", "error": str(exc)}
    print("__CAPTAIN_RESULT__" + json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
