"""一次性 WebSocket 冒烟测试:验证 server 的流式 + 确认卡片往返。"""
import asyncio
import json
import os

import websockets


async def main() -> int:
    uri = "ws://127.0.0.1:8000/ws"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "user", "text": "写 logs/ws.txt :: hello-web"}))
        events = []
        approved_sent = False
        while True:
            ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            events.append(ev)
            t = ev["type"]
            print("EVENT:", t, ev["payload"])
            if t == "approval_request" and not approved_sent:
                await ws.send(json.dumps({"type": "approval", "approved": True}))
                approved_sent = True
            if t == "task_done":
                break

    saw_request = any(e["type"] == "approval_request" for e in events)
    result = next((e for e in events if e["type"] == "capability_result"), None)
    wrote_ok = result and result["payload"].get("ok")
    file_ok = os.path.isfile("logs/ws.txt")
    ok = saw_request and wrote_ok and file_ok
    print("---")
    print(f"确认卡片={saw_request}, 写入成功={wrote_ok}, 文件存在={file_ok}")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
