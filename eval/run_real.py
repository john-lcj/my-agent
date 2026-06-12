"""真实任务评测 —— 用真模型跑 eval/personal/tasks.yaml,LLM-as-judge 打分。

MockLLM 回归保证"水管不漏",本评测回答"答案好不好"。每周跑一遍,
报告落在 logs/eval_reports/YYYY-MM-DD.md,自动与上一份对比。

用法:
    .venv/bin/python -m eval.run_real                 # 全量
    .venv/bin/python -m eval.run_real --only code-explain
    .venv/bin/python -m eval.run_real --model deepseek-v4-pro
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config, load_env

TASKS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "personal", "tasks.yaml")
REPORT_DIR = os.path.join(Config.LOG_DIR, "eval_reports")

_JUDGE_PROMPT = """你是严格的 agent 评测官。根据评分要点给 agent 的回答打分。

【任务】
{prompt}

【评分要点】
{rubric}

【agent 的回答】
{answer}

注:若回答末尾附有「agent 实际产出的文件」段,说明这些文件已**真实写入磁盘**,
请据此核验产物是否存在、是否满足要求;若任务要求产出文件却未见该段,则产物不存在。

打分标准:5=完全满足要点且超出预期;4=满足全部要点;3=满足主要要点有小缺陷;
2=部分满足;1=基本未满足或答非所问。

严格只输出 JSON(不要其他内容):
{{"score": 1到5的整数, "comment": "30字内点评"}}"""


def _load_tasks() -> list[dict]:
    import yaml
    with open(TASKS_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("tasks") or []


async def _run_task(prompt: str, model: str | None) -> str:
    """每个任务用独立的 coordinator 栈跑(互不污染上下文)。"""
    from core.coordinator_stack import build_coordinator_stack
    from core.types import Identity
    from memory.factory import build_longterm

    coordinator, bundle = build_coordinator_stack(
        Identity(subject_id="eval-real", channel="eval"),
        profile="interactive",
        longterm=build_longterm(Config.LOG_DIR),
        model=model,
    )

    async def auto_confirm(call, decision, reason=""):
        return True

    return await coordinator.run(prompt, bundle.ctx, auto_confirm)


_ARTIFACT_EXT = (".html", ".htm", ".css", ".js", ".md", ".txt", ".json", ".csv", ".svg", ".py")


def _artifact_completeness(text: str, path: str) -> str:
    """对产物做"完整性体检",让评委不被截断误导成'文件不完整'。"""
    low = text.lower()
    flags = []
    if path.lower().endswith((".html", ".htm")):
        flags.append(f"DOCTYPE={'✓' if '<!doctype html' in low else '✗'}")
        flags.append(f"闭合</html>={'✓' if '</html>' in low else '✗'}")
        flags.append(f"闭合</body>={'✓' if '</body>' in low else '✗'}")
        flags.append(f"内联<style>={'✓' if '<style' in low else '✗'}")
    return " ".join(flags)


def _excerpt(text: str, head: int = 2800, tail: int = 1500) -> str:
    """大文件取头+尾,中间省略——既能判完整性,又不被截断误判。"""
    if len(text) <= head + tail:
        return text
    return (text[:head]
            + f"\n\n…(中间省略 {len(text) - head - tail} 字符)…\n\n"
            + text[-tail:])


def _collect_artifacts(answer: str, max_files: int = 3) -> str:
    """从回答里抓出文件路径,把**磁盘上真实存在**的产物读出来给评委核验。

    真产出 → 评委看到文件头尾 + 完整性体检;凭空编造的路径 → 文件不存在 → 落空、应判低分。
    """
    cands: set[str] = set(re.findall(r"`([^`\n]+)`", answer or ""))
    cands |= set(re.findall(r"(?:^|\s)((?:~|\./|/)[\w./ \-]+\.\w{1,5})", answer or ""))
    blocks: list[str] = []
    seen: set[str] = set()
    for raw in cands:
        p = raw.strip().strip("`").strip()
        if not p.lower().endswith(_ARTIFACT_EXT):
            continue
        path = os.path.expanduser(p)
        if not os.path.isabs(path):
            path = os.path.abspath(path)
        if path in seen or not os.path.isfile(path):
            continue
        seen.add(path)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            continue
        size = os.path.getsize(path)
        check = _artifact_completeness(content, p)
        header = f"--- 文件 {p}({size} 字节;{check})---" if check else f"--- 文件 {p}({size} 字节)---"
        blocks.append(f"{header}\n{_excerpt(content)}")
        if len(blocks) >= max_files:
            break
    return "\n\n".join(blocks)


async def _judge(task: dict, answer: str, model: str | None) -> tuple[int, str]:
    from core.types import Message, Role
    from llm.factory import build_llm

    llm = build_llm(model=model)
    judge_answer = (answer or "")[:4000]
    artifacts = _collect_artifacts(answer or "")
    if artifacts:
        judge_answer += "\n\n【agent 实际产出的文件(从磁盘读取,用于核验;大文件取头尾+完整性体检)】\n" + artifacts[:12000]
    prompt = _JUDGE_PROMPT.format(
        prompt=task["prompt"], rubric=task["rubric"], answer=judge_answer)
    step = await llm.next_step([Message(role=Role.USER, content=prompt)], [])
    m = re.search(r"\{.*\}", step.text or "", re.DOTALL)
    if not m:
        return 0, "评委输出无法解析"
    try:
        data = json.loads(m.group())
        return int(data.get("score", 0)), str(data.get("comment", ""))[:60]
    except Exception as e:
        return 0, f"解析失败:{e}"


def _previous_avg() -> tuple[str, float] | None:
    """读取最近一份报告的平均分,用于对比。"""
    if not os.path.isdir(REPORT_DIR):
        return None
    reports = sorted(f for f in os.listdir(REPORT_DIR) if f.endswith(".md"))
    if not reports:
        return None
    last = reports[-1]
    try:
        with open(os.path.join(REPORT_DIR, last), "r", encoding="utf-8") as f:
            m = re.search(r"平均分[::]\s*([\d.]+)", f.read())
        return (last, float(m.group(1))) if m else None
    except Exception:
        return None


async def main() -> int:
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="只跑指定 id 的任务")
    parser.add_argument("--model", help="指定模型 id(默认用 AGENT_MODEL)")
    args = parser.parse_args()

    if Config.PROVIDER == "mock" and not args.model:
        print("AGENT_PROVIDER=mock 跑不出有意义的评测,请配置真实模型或用 --model 指定。")
        return 1

    tasks = _load_tasks()
    if args.only:
        tasks = [t for t in tasks if t["id"] == args.only]
    if not tasks:
        print("没有可跑的任务")
        return 1

    prev = _previous_avg()
    rows: list[dict] = []
    print(f"开始评测 {len(tasks)} 个任务(模型: {args.model or Config.MODEL})")
    print("=" * 56)

    for t in tasks:
        t0 = time.time()
        try:
            answer = await _run_task(t["prompt"], args.model)
        except Exception as e:
            answer = f"(执行异常: {e})"
        try:
            score, comment = await _judge(t, answer, args.model)
        except Exception as e:
            score, comment = 0, f"评委异常:{e}"
        elapsed = time.time() - t0
        rows.append({"id": t["id"], "score": score, "comment": comment,
                     "elapsed": elapsed, "answer": answer})
        print(f" [{score}/5] {t['id']}  ({elapsed:.0f}s)  {comment}")

    scored = [r for r in rows if r["score"] > 0]
    avg = sum(r["score"] for r in scored) / len(scored) if scored else 0.0

    os.makedirs(REPORT_DIR, exist_ok=True)
    today = datetime.date.today().isoformat()
    report_path = os.path.join(REPORT_DIR, f"{today}.md")
    lines = [
        f"# 真实任务评测报告 {today}",
        "",
        f"- 模型: {args.model or Config.MODEL}",
        f"- 任务数: {len(rows)}(有效评分 {len(scored)})",
        f"- 平均分: {avg:.2f}",
    ]
    if prev:
        delta = avg - prev[1]
        trend = "↑ 变好" if delta > 0.05 else ("↓ 变差" if delta < -0.05 else "→ 持平")
        lines.append(f"- 与上次({prev[0]},{prev[1]:.2f})对比: {delta:+.2f} {trend}")
    lines += ["", "| 任务 | 得分 | 点评 | 耗时 |", "|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['id']} | {r['score']}/5 | {r['comment']} | {r['elapsed']:.0f}s |")
    lines += ["", "## 回答全文", ""]
    for r in rows:
        lines += [f"### {r['id']}({r['score']}/5)", "", (r["answer"] or "")[:2000], ""]

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("-" * 56)
    print(f"平均分 {avg:.2f}/5,报告: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
