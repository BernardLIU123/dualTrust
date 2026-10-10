"""Notifier：钉钉 webhook 载荷、静默模式、邮件走通性。"""
import json
import smtplib

from notifier import Notifier


class FakeResp:
    def read(self):
        return json.dumps({"errcode": 0}).encode("utf-8")


def test_disabled_is_silent(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req)

    monkeypatch.setattr("notifier.urllib.request.urlopen", fake_urlopen)
    Notifier(enabled=False).send("t", "x")
    assert calls == []


def test_dingtalk_payload(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["data"] = json.loads(req.data.decode("utf-8"))
        captured["url"] = req.full_url
        return FakeResp()

    monkeypatch.setattr("notifier.urllib.request.urlopen", fake_urlopen)
    n = Notifier(dingtalk_webhook="https://oapi.dingtalk.com/robot/send?access_token=abc")
    n.critical("持仓不一致", "核心 LONG 仓位 0")
    assert captured["url"].startswith("https://oapi.dingtalk.com")
    md = captured["data"]["markdown"]
    assert md["title"].startswith("[CRITICAL]")
    assert "持仓不一致" in md["text"]


def test_dingtalk_error_raises(monkeypatch):
    class BadResp:
        def read(self):
            return json.dumps({"errcode": 310000}).encode("utf-8")

    monkeypatch.setattr("notifier.urllib.request.urlopen", lambda req, timeout=None: BadResp())
    import pytest
    n = Notifier(dingtalk_webhook="https://example.com/robot")
    with pytest.raises(RuntimeError, match="钉钉推送失败"):
        n.send("t", "x")


def test_email_sent(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            self.host, self.port = host, port
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def login(self, u, p):
            sent["login"] = (u, p)
        def sendmail(self, frm, to, msg):
            sent["mail"] = (frm, to, msg)

    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    cfg = {"host": "smtp.example.com", "port": 465, "username": "u",
           "password": "p", "from_addr": "a@x.com", "to_addr": "b@x.com"}
    Notifier(smtp_config=cfg).warn("强平预警", "14:50 仍持仓")
    assert sent["login"] == ("u", "p")
    assert "[WARN]" in sent["mail"][2]
