#!/usr/bin/env python3
"""Captain License Server — 管理员 CLI

用法（在 VPS 上或本地运行）：
  python admin_cli.py gen   [--n 5] [--months 12] [--plan pro]
  python admin_cli.py issue --email buyer@example.com [--months 12]
  python admin_cli.py list
  python admin_cli.py send  --email buyer@example.com --key CAPT-PRO-XXXX-XXXX-XXXX

环境变量（或直接在脚本里填）：
  LICENSE_SERVER   服务器地址，如 https://license.captain-ai.com
  ADMIN_TOKEN      管理员 token
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

SERVER = os.environ.get("LICENSE_SERVER", "http://localhost:8080")
TOKEN  = os.environ.get("ADMIN_TOKEN", "")


def _post(path: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req  = urllib.request.Request(
        f"{SERVER}{path}", data=data,
        headers={"Content-Type": "application/json", "X-Admin-Token": TOKEN},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _get(path: str) -> dict:
    req = urllib.request.Request(
        f"{SERVER}{path}",
        headers={"X-Admin-Token": TOKEN},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def cmd_gen(args):
    """批量生成授权码。"""
    r = _post("/api/license/generate", {
        "plan":   args.plan,
        "months": args.months,
        "n":      args.n,
        "note":   args.note,
    })
    if not r.get("ok"):
        print(f"✗ {r.get('error')}")
        sys.exit(1)
    print(f"✓ 生成 {len(r['keys'])} 个授权码：")
    for k in r["keys"]:
        print(f"  {k}")


def cmd_issue(args):
    """向买家邮箱发码（管理员手动补发）。"""
    r = _post("/api/payment/manual_issue", {
        "email":  args.email,
        "plan":   args.plan,
        "months": args.months,
        "note":   args.note or "manual-cli",
    })
    if not r.get("ok"):
        print(f"✗ {r.get('error')}")
        sys.exit(1)
    print(f"✓ 已向 {args.email} 发送授权码：{r['key']}")


def cmd_list(args):
    """查看所有授权码。"""
    r = _get("/api/license/list")
    if not r.get("ok"):
        print(f"✗ {r.get('error')}")
        sys.exit(1)
    keys = r.get("keys", [])
    if not keys:
        print("（暂无记录）")
        return
    print(f"{'授权码':<35} {'套餐':<6} {'月数':>4} {'激活数':>5} {'备注'}")
    print("-" * 70)
    for k in keys:
        from datetime import datetime
        exp = datetime.fromtimestamp(k["expires_at"]).strftime("%Y-%m-%d") if k.get("expires_at") else "永久"
        print(f"{k['key']:<35} {k['plan']:<6} {k['months']:>4}  {k['activations']:>5}  {k.get('note','')[:20]}")


def cmd_send(args):
    """仅重发邮件（不生成新 key）。"""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from mailer import send, render_key_email
    except ImportError:
        print("✗ 请在 license_server/ 目录下运行此脚本")
        sys.exit(1)
    months = args.months
    subj, html, text = render_key_email(args.key, "pro", months, None)
    ok = send(args.email, subj, html, text)
    if ok:
        print(f"✓ 邮件已发送至 {args.email}")
    else:
        print("✗ 发送失败，检查 SMTP 配置")


def main():
    if not TOKEN:
        print("⚠  ADMIN_TOKEN 未设置，请先: export ADMIN_TOKEN=your-token")

    p = argparse.ArgumentParser(description="Captain License Admin CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    # gen
    g = sub.add_parser("gen", help="批量生成授权码")
    g.add_argument("--n",      type=int, default=1,    help="数量")
    g.add_argument("--months", type=int, default=12,   help="有效期（月）")
    g.add_argument("--plan",   default="pro")
    g.add_argument("--note",   default="")

    # issue
    i = sub.add_parser("issue", help="向买家发码（手动补发）")
    i.add_argument("--email",  required=True)
    i.add_argument("--months", type=int, default=12)
    i.add_argument("--plan",   default="pro")
    i.add_argument("--note",   default="")

    # list
    sub.add_parser("list", help="查看所有授权码")

    # send
    s = sub.add_parser("send", help="重发授权码邮件")
    s.add_argument("--email",  required=True)
    s.add_argument("--key",    required=True)
    s.add_argument("--months", type=int, default=12)

    args = p.parse_args()
    {"gen": cmd_gen, "issue": cmd_issue, "list": cmd_list, "send": cmd_send}[args.cmd](args)


if __name__ == "__main__":
    main()
