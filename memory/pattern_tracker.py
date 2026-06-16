"""任务模式追踪 —— 自我改进闭环的"发现"环节。

记录主人交办的任务,把相似的归到一类并计数。当某类任务**反复出现**(达到阈值)、
且还没被固化成 skill 时,在下次开场提示 Captain:"这类活你已干过 N 次,要不要用
skill_author 固化成一个 skill 以后一键复用?"——人确认后由 Captain 实际撰写 skill。

相似度用字符 bigram 的 Jaccard(对中文无需分词即可粗略聚类)。状态存 logs/task_patterns.json。
全程无 LLM、失败静默,绝不拖累主流程。
"""
from __future__ import annotations

import json
import os
import re
import time

_THRESHOLD = 3       # 同类任务出现达到这么多次,才建议固化
_SIM = 0.35          # Jaccard 相似度阈值:>= 视为同一类(中文不同措辞也能聚到一起)
_MIN_LEN = 4         # 太短的任务文本不追踪(如"你好")


def _signature(text: str) -> set:
    """字符 bigram + 英文单词,作为相似度比较的特征集合。"""
    cleaned = re.sub(r"[\s\W_]+", "", (text or "").lower())
    grams = {cleaned[i:i + 2] for i in range(len(cleaned) - 1)}
    grams |= set(re.findall(r"[a-z]{2,}", (text or "").lower()))
    return grams


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / len(a | b)


class PatternTracker:
    def __init__(self, path: str = "logs/task_patterns.json") -> None:
        self.path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._data = self._read()

    def _read(self) -> list:
        if not os.path.isfile(self.path):
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f) or []
        except Exception:
            return []

    def _write(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def record(self, task: str) -> None:
        """记录一次任务;归入最相似的已有类,或新建一类。"""
        task = (task or "").strip()
        if len(task) < _MIN_LEN:
            return
        sig = _signature(task)
        best, best_sim = None, 0.0
        for c in self._data:
            s = _jaccard(sig, set(c.get("_sig", [])))
            if s > best_sim:
                best, best_sim = c, s
        if best is not None and best_sim >= _SIM:
            best["count"] = int(best.get("count", 1)) + 1
            best["last"] = task[:120]
        else:
            self._data.append({
                "rep": task[:120], "last": task[:120], "count": 1,
                "crystallized": False, "_sig": sorted(sig),
                "ts": time.strftime("%Y-%m-%d %H:%M"),
            })
        self._write()

    def suggestion_for(self, task: str) -> str:
        """当前任务若命中"已反复出现且未固化"的类,返回一句固化建议;否则空串。"""
        sig = _signature(task or "")
        if len(sig) < 2:
            return ""
        for c in self._data:
            if c.get("crystallized"):
                continue
            if int(c.get("count", 0)) < _THRESHOLD:
                continue
            if _jaccard(sig, set(c.get("_sig", []))) >= _SIM:
                return (f"[自我改进提示] 类似「{c.get('rep', '')[:40]}」的任务你已交办约 "
                        f"{c.get('count')} 次。若以后还会重复,完成本次后可主动问主人:"
                        f"要不要用 skill.skill_author 把它固化成一个可复用的 skill。")
        return ""

    def mark_crystallized(self, task: str) -> None:
        sig = _signature(task or "")
        for c in self._data:
            if _jaccard(sig, set(c.get("_sig", []))) >= _SIM:
                c["crystallized"] = True
        self._write()
