"""邮件发送模块 — 纯 stdlib smtplib，零依赖。

支持：
  - QQ 邮箱 SMTP（推荐，申请授权码即可）
  - 163 / 126 邮箱
  - Gmail（需开启"应用专用密码"）
  - 任意 SMTP 服务

配置（环境变量）：
  SMTP_HOST     SMTP 服务器，如 smtp.qq.com
  SMTP_PORT     端口，默认 465（SSL）
  SMTP_USER     发件人邮箱
  SMTP_PASS     邮箱授权码（不是登录密码）
  SMTP_FROM     显示名称，默认 "Captain AI"
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

_HOST  = os.environ.get("SMTP_HOST", "smtp.qq.com")
_PORT  = int(os.environ.get("SMTP_PORT", "465"))
_USER  = os.environ.get("SMTP_USER", "")
_PASS  = os.environ.get("SMTP_PASS", "")
_FROM  = os.environ.get("SMTP_FROM", "Captain AI")


def send(to: str, subject: str, html: str, text: str = "") -> bool:
    """发送邮件，返回 True 表示成功。失败时打印错误但不抛出。"""
    if not _USER or not _PASS:
        print(f"[mailer] SMTP 未配置，跳过发送邮件到 {to}")
        print(f"[mailer] 邮件内容预览：{subject}\n{text or html[:200]}")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"{_FROM} <{_USER}>"
        msg["To"]      = to
        if text:
            msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))

        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(_HOST, _PORT, context=ctx, timeout=10) as s:
            s.login(_USER, _PASS)
            s.sendmail(_USER, [to], msg.as_bytes())
        print(f"[mailer] ✓ 邮件已发送至 {to}")
        return True
    except Exception as e:
        print(f"[mailer] ✗ 发送失败 ({to}): {e}")
        return False


# ── 邮件模板 ──────────────────────────────────────────────────────────────────

def render_key_email(key: str, plan: str, months: int, expires_at: Optional[float]) -> tuple[str, str, str]:
    """返回 (subject, html, text)"""
    plan_cn  = "Pro 年付" if months >= 12 else "Pro 月付"
    days     = months * 30
    subject  = f"🎉 您的 Captain {plan_cn}授权码"

    html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#f4f4f8;font-family:-apple-system,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="padding:40px 16px;">
<table width="560" cellpadding="0" cellspacing="0"
  style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.08);">
  <!-- header -->
  <tr><td style="background:#7c6cf0;padding:32px;text-align:center;">
    <div style="font-size:28px;font-weight:800;color:#fff;letter-spacing:-1px;">⚡ Captain</div>
    <div style="color:#c5beff;font-size:14px;margin-top:6px;">私人 AI Agent</div>
  </td></tr>
  <!-- body -->
  <tr><td style="padding:36px 40px;">
    <p style="font-size:16px;color:#333;margin:0 0 24px;">感谢购买 Captain <b>{plan_cn}</b>！</p>
    <p style="font-size:14px;color:#555;margin:0 0 12px;">您的授权码：</p>
    <div style="background:#f0eeff;border:2px dashed #7c6cf0;border-radius:10px;
                padding:18px;text-align:center;margin-bottom:28px;">
      <code style="font-size:22px;font-weight:700;color:#5048cc;letter-spacing:2px;">{key}</code>
    </div>
    <p style="font-size:14px;color:#555;margin:0 0 8px;"><b>激活方式：</b></p>
    <div style="background:#f8f8fc;border-radius:8px;padding:16px;margin-bottom:24px;">
      <code style="font-size:13px;color:#333;white-space:pre;">python -m license_client.cli activate {key}</code>
    </div>
    <p style="font-size:14px;color:#555;margin:0 0 24px;">
      有效期 <b>{days} 天</b>，支持 <b>2 台设备</b>同时激活。<br/>
      如需帮助，回复此邮件即可。
    </p>
    <div style="border-top:1px solid #eee;padding-top:20px;">
      <p style="font-size:13px;color:#999;margin:0;">
        ⚠️ 请妥善保管授权码，不要分享给他人。<br/>
        7 天内如不满意，回复此邮件申请全额退款。
      </p>
    </div>
  </td></tr>
  <!-- footer -->
  <tr><td style="background:#fafafa;padding:20px 40px;text-align:center;">
    <p style="font-size:12px;color:#bbb;margin:0;">
      © 2025 Captain AI · <a href="https://captain-ai.com" style="color:#7c6cf0;">captain-ai.com</a>
    </p>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""

    text = f"""感谢购买 Captain {plan_cn}！

授权码：{key}

激活方式（在 Captain 安装目录运行）：
  python -m license_client.cli activate {key}

有效期：{days} 天 / 支持 2 台设备

如有问题，回复此邮件即可。7 天无理由退款。

© 2025 Captain AI
"""
    return subject, html, text
