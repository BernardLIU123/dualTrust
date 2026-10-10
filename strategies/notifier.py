"""告警推送：钉钉机器人 + 可选 SMTP 邮件。webhook 未配置时静默（开发/回测模式）。"""
from __future__ import annotations

import json
import smtplib
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from typing import Optional


class Notifier:
    def __init__(self, dingtalk_webhook: str = "", smtp_config: Optional[dict] = None,
                 enabled: bool = True):
        self.dingtalk_webhook = dingtalk_webhook
        self.smtp_config = smtp_config or {}
        self.enabled = enabled

    def info(self, title: str, text: str = "") -> None:
        self.send(title, text, "INFO")

    def warn(self, title: str, text: str = "") -> None:
        self.send(title, text, "WARN")

    def critical(self, title: str, text: str = "") -> None:
        self.send(title, text, "CRITICAL")

    def send(self, title: str, text: str = "", level: str = "INFO") -> None:
        if not self.enabled:
            return
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if self.dingtalk_webhook:
            self._send_dingtalk(ts, title, text, level)
        if self.smtp_config.get("host"):
            self._send_email(ts, title, text, level)

    def _send_dingtalk(self, ts: str, title: str, text: str, level: str) -> None:
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": f"[{level}] {title}",
                "text": f"### [{level}] {title}\n\n{text}\n\n> {ts}",
            },
        }
        req = urllib.request.Request(
            self.dingtalk_webhook,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=5)
        try:
            result = json.loads(resp.read().decode("utf-8"))
        finally:
            if hasattr(resp, "close"):
                resp.close()
        if result.get("errcode") != 0:
            raise RuntimeError(f"钉钉推送失败: {result}")

    def _send_email(self, ts: str, title: str, text: str, level: str) -> None:
        cfg = self.smtp_config
        msg = EmailMessage()
        msg.set_content(f"[{level}] {title}\n\n{text}\n\n{ts}", subtype="plain",
                        charset="utf-8", cte="quoted-printable")
        msg["Subject"] = f"[DualThrust][{level}] {title}"
        msg["From"] = cfg["from_addr"]
        msg["To"] = cfg["to_addr"]
        with smtplib.SMTP_SSL(cfg["host"], cfg.get("port", 465), timeout=10) as server:
            server.login(cfg["username"], cfg["password"])
            server.sendmail(cfg["from_addr"], [cfg["to_addr"]], msg.as_string())
