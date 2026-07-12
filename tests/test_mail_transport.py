from __future__ import annotations

import asyncio
import json
import os
import smtplib

from channels import mail_transport
from channels.email_channel import EmailChannel, _transient_smtp_error


def test_fakeip_mail_uses_direct_macos_connection(monkeypatch):
    marker = object()
    monkeypatch.setattr(mail_transport.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(mail_transport, "host_uses_fake_ip", lambda _host: True)
    monkeypatch.setattr(mail_transport, "_direct_macos_connection", lambda *_args: marker)
    assert mail_transport.create_mail_connection("imap.example.com", 993, 10) is marker


def test_normal_dns_uses_standard_connection(monkeypatch):
    marker = object()
    monkeypatch.setattr(mail_transport.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(mail_transport, "host_uses_fake_ip", lambda _host: False)
    monkeypatch.setattr(mail_transport.socket, "create_connection", lambda *_args: marker)
    assert mail_transport.create_mail_connection("imap.example.com", 993, 10) is marker


def test_authentication_error_is_not_retryable():
    exc = smtplib.SMTPAuthenticationError(535, b"bad credentials")
    assert _transient_smtp_error(exc) is False
    assert _transient_smtp_error(OSError("temporary network failure")) is True


def test_failed_transient_send_is_persisted_for_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    channel = EmailChannel(
        imap_host="imap.example.com",
        smtp_host="smtp.example.com",
        user="captain@example.com",
        password="secret",
    )

    def fail(*_args, **_kwargs):
        raise OSError("network unavailable")

    monkeypatch.setattr(channel, "_send_sync", fail)
    sent = asyncio.run(channel._send_email("owner@example.com", "Subject", "Body"))
    assert sent is False
    path = tmp_path / "logs" / "email_outbox.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    assert entries[0]["to"] == "owner@example.com"
    assert entries[0]["body"] == "Body"
    assert os.stat(path).st_mode & 0o077 == 0


def test_outbox_removes_successful_delivery(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    channel = EmailChannel(
        imap_host="imap.example.com",
        smtp_host="smtp.example.com",
        user="captain@example.com",
        password="secret",
    )
    channel._queue_outbound("delivery-1", "owner@example.com", "Subject", "Body", [], OSError("x"))
    path = tmp_path / "logs" / "email_outbox.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    entries[0]["next_attempt_at"] = 0
    path.write_text(json.dumps(entries), encoding="utf-8")
    monkeypatch.setattr(channel, "_send_sync", lambda *_args, **_kwargs: None)
    channel._flush_outbox_sync()
    assert json.loads(path.read_text(encoding="utf-8")) == []
