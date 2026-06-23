"""分享快照存储 —— 把一段对话或一个产物固化成只读快照,生成可访问链接。

快照是当下内容的拷贝(不随原会话变动/删除而变),用随机 token 当链接,
对应公开只读页 /share/<token>。主人显式分享才创建。
"""
from __future__ import annotations

import json
import os
import secrets
import time


class ShareStore:
    def __init__(self, path: str = "logs/shares.json") -> None:
        self.path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def _read(self) -> dict:
        if not os.path.isfile(self.path):
            return {}
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _write(self, data: dict) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def create(self, kind: str, title: str, payload: dict) -> str:
        """kind: conversation | artifact。payload 是快照内容。返回 token。"""
        token = secrets.token_urlsafe(12)
        data = self._read()
        data[token] = {"kind": kind, "title": title, "payload": payload,
                       "created": time.time()}
        # 控制总量
        if len(data) > 500:
            for k in sorted(data, key=lambda x: data[x]["created"])[:100]:
                data.pop(k, None)
        self._write(data)
        return token

    def get(self, token: str) -> dict | None:
        return self._read().get(token)

    def delete(self, token: str) -> bool:
        data = self._read()
        if token in data:
            data.pop(token)
            self._write(data)
            return True
        return False
