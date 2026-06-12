"""个人数据接入(只读)—— 把你的笔记/文档目录索引进长期记忆,供语义检索。

专属 agent 的壁垒是数据不是代码:接入你的真实笔记后,"我之前怎么想的"
"我笔记里写过什么"这类问题才答得出来。

设计:
  - 只读:本模块只读取目录内容,绝不写入/修改源文件。
  - 增量:按文件 mtime 记录状态(JSON),没变的文件跳过;变了先删旧块再重索引。
  - 块标记:每块内容以 [file:<路径>] 开头,既是删除锚点,也让检索结果可溯源。
"""
from __future__ import annotations

import json
import os

from memory.base import MemoryItem

KIND = "personal_doc"
_EXTS = {".md", ".markdown", ".txt"}
_CHUNK_CHARS = 600
_MAX_CHUNKS_PER_FILE = 60
_MAX_FILE_BYTES = 2 * 1024 * 1024  # 超大文件跳过


def ingest_dirs(dirs: list[str], memory, state_path: str) -> dict:
    """扫描目录增量索引。返回统计 {scanned, indexed, skipped, removed_chunks}。"""
    state = _load_state(state_path)
    stats = {"scanned": 0, "indexed": 0, "skipped": 0, "removed_chunks": 0}

    seen_files: set[str] = set()
    for root_dir in dirs:
        if not os.path.isdir(root_dir):
            continue
        for dirpath, dirnames, filenames in os.walk(root_dir):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fname in filenames:
                if fname.startswith(".") or os.path.splitext(fname)[1].lower() not in _EXTS:
                    continue
                fpath = os.path.abspath(os.path.join(dirpath, fname))
                seen_files.add(fpath)
                stats["scanned"] += 1
                try:
                    mtime = os.path.getmtime(fpath)
                    if os.path.getsize(fpath) > _MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                if state.get(fpath) == mtime:
                    stats["skipped"] += 1
                    continue
                stats["removed_chunks"] += _remove_file_chunks(memory, fpath)
                n = _index_file(memory, fpath)
                if n > 0:
                    state[fpath] = mtime
                    stats["indexed"] += 1

    # 源文件已删除的,清掉对应索引与状态
    for fpath in [p for p in state if p not in seen_files]:
        stats["removed_chunks"] += _remove_file_chunks(memory, fpath)
        del state[fpath]

    _save_state(state_path, state)
    return stats


def _index_file(memory, fpath: str) -> int:
    try:
        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return 0
    chunks = _chunk(text)
    for i, chunk in enumerate(chunks[:_MAX_CHUNKS_PER_FILE]):
        memory.store(MemoryItem(
            kind=KIND,
            content=f"[file:{fpath}#{i}] {chunk}",
            importance=0.5,
            source="user",
        ))
    return len(chunks)


def _remove_file_chunks(memory, fpath: str) -> int:
    fn = getattr(memory, "delete_by_content_prefix", None)
    return fn(KIND, f"[file:{fpath}#") if callable(fn) else 0


def _chunk(text: str, size: int = _CHUNK_CHARS) -> list[str]:
    """按段落聚合成 ~size 字的块,段落过长则硬切。"""
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paras:
        while len(p) > size:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(p[:size])
            p = p[size:]
        if len(buf) + len(p) + 1 > size and buf:
            chunks.append(buf)
            buf = p
        else:
            buf = f"{buf}\n{p}" if buf else p
    if buf:
        chunks.append(buf)
    return chunks


def _load_state(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save_state(path: str, state: dict) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=0)
