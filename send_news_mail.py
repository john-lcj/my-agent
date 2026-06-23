#!/usr/bin/env python3
"""
AI 科技新闻邮件发送脚本

用法:
  python send_news_mail.py --content "新闻正文..."
  python send_news_mail.py --file /path/to/news.md

通过 SMTP 将新闻内容发送到 luchangjie@outlook.com，标题包含日期。
SMTP 配置从环境变量读取（EMAIL_SMTP_HOST, EMAIL_USER, EMAIL_PASS 等）。
"""

import argparse
import os
import smtplib
import ssl
import sys
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText


def get_today_label() -> str:
    """返回当前日期（用于邮件标题），格式 YYYY-MM-DD"""
    # 按任务描述，发送"前一天的"新闻，所以标题用昨天日期
    tz = timezone(timedelta(hours=8))  # 北京时间
    yesterday = datetime.now(tz) - timedelta(days=1)
    return yesterday.strftime("%Y-%m-%d")


def send_mail(
    to: str,
    subject: str,
    body: str,
    *,
    smtp_host: str = "",
    smtp_port: int = 465,
    smtp_user: str = "",
    smtp_password: str = "",
) -> dict:
    """通过 SMTP_SSL 发送邮件"""
    if not smtp_host:
        return {"success": False, "error": "EMAIL_SMTP_HOST 未配置"}
    if not smtp_user:
        return {"success": False, "error": "EMAIL_USER 未配置"}
    if not smtp_password:
        return {"success": False, "error": "EMAIL_PASS 未配置"}

    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = smtp_user
    msg["To"] = to
    msg["Subject"] = subject

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ctx) as s:
            s.login(smtp_user, smtp_password)
            s.send_message(msg)
        return {"success": True, "to": to, "subject": subject}
    except smtplib.SMTPAuthenticationError:
        return {"success": False, "error": "SMTP 认证失败，请检查 EMAIL_USER / EMAIL_PASS"}
    except smtplib.SMTPException as e:
        return {"success": False, "error": f"SMTP 错误: {e}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="发送 AI 科技新闻邮件")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--content", type=str, help="直接传入新闻正文")
    group.add_argument("--file", type=str, help="新闻 Markdown 文件路径")
    parser.add_argument("--to", type=str, default="luchangjie@outlook.com", help="收件人，默认 luchangjie@outlook.com")
    parser.add_argument("--date", type=str, default="", help="手动指定日期标签（可选），默认取昨天日期")
    parser.add_argument("--subject-prefix", type=str, default="AI 科技新闻日报", help="邮件标题前缀")
    args = parser.parse_args()

    # 读取正文
    if args.content:
        body = args.content
        source_desc = "命令行参数"
    elif args.file:
        fpath = args.file
        if not os.path.isfile(fpath):
            print(f"❌ 文件不存在: {fpath}", file=sys.stderr)
            sys.exit(1)
        with open(fpath, "r", encoding="utf-8") as f:
            body = f.read()
        source_desc = f"文件 {fpath}"
    else:
        print("❌ 请提供 --content 或 --file", file=sys.stderr)
        sys.exit(1)

    # 标题日期
    date_label = args.date if args.date else get_today_label()
    subject = f"{args.subject_prefix} | {date_label}"

    # SMTP 配置从环境变量读取
    smtp_host = os.environ.get("EMAIL_SMTP_HOST", "").strip()
    smtp_port = int(os.environ.get("EMAIL_SMTP_PORT", "465"))
    smtp_user = os.environ.get("EMAIL_USER", "").strip()
    smtp_password = os.environ.get("EMAIL_PASS", "").strip()

    print(f"📧 收件人: {args.to}")
    print(f"📋 标题: {subject}")
    print(f"📄 正文来源: {source_desc}")
    print(f"🔌 SMTP: {smtp_host}:{smtp_port} / {smtp_user}")
    print()

    result = send_mail(
        to=args.to,
        subject=subject,
        body=body,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_user=smtp_user,
        smtp_password=smtp_password,
    )

    if result.get("success"):
        print(f"✅ 邮件发送成功 → {result['to']}")
        print(f"📋 标题: {result['subject']}")
    else:
        print(f"❌ 邮件发送失败: {result.get('error')}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
