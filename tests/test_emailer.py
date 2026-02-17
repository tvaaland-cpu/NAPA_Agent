from __future__ import annotations

from types import SimpleNamespace

from napa_agent.notify.emailer import send_email


class FakeSMTP:
    def __init__(self, *_args, **_kwargs):
        self.actions: list[str] = []
        self.logged_in_with: tuple[str, str] | None = None
        self.message = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def ehlo(self):
        self.actions.append("ehlo")

    def starttls(self, **_kwargs):
        self.actions.append("starttls")

    def login(self, user: str, password: str):
        self.logged_in_with = (user, password)

    def send_message(self, message):
        self.message = message


class Recorder:
    def __init__(self):
        self.smtp_instance = FakeSMTP()
        self.smtp_ssl_instance = FakeSMTP()

    def smtp(self, *_args, **_kwargs):
        return self.smtp_instance

    def smtp_ssl(self, *_args, **_kwargs):
        return self.smtp_ssl_instance


def test_send_email_uses_starttls_for_587(monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr("napa_agent.notify.emailer.smtplib.SMTP", recorder.smtp)
    monkeypatch.setattr("napa_agent.notify.emailer.smtplib.SMTP_SSL", recorder.smtp_ssl)

    settings = SimpleNamespace(
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_user="user@example.com",
        smtp_password="secret",
        smtp_from="from@example.com",
        smtp_to="to@example.com",
    )

    send_email(settings, "subject", "body")

    assert recorder.smtp_instance.actions == ["ehlo", "starttls", "ehlo"]
    assert recorder.smtp_instance.logged_in_with == ("user@example.com", "secret")
    assert recorder.smtp_ssl_instance.message is None


def test_send_email_uses_ssl_for_465(monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr("napa_agent.notify.emailer.smtplib.SMTP", recorder.smtp)
    monkeypatch.setattr("napa_agent.notify.emailer.smtplib.SMTP_SSL", recorder.smtp_ssl)

    settings = SimpleNamespace(
        smtp_host="smtp.gmail.com",
        smtp_port=465,
        smtp_user="user@example.com",
        smtp_password="secret",
        smtp_from="from@example.com",
        smtp_to="to@example.com",
    )

    send_email(settings, "subject", "body")

    assert recorder.smtp_ssl_instance.logged_in_with == ("user@example.com", "secret")
    assert recorder.smtp_instance.message is None


def test_send_email_attaches_html_alternative(monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr("napa_agent.notify.emailer.smtplib.SMTP", recorder.smtp)
    monkeypatch.setattr("napa_agent.notify.emailer.smtplib.SMTP_SSL", recorder.smtp_ssl)

    settings = SimpleNamespace(
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_user="user@example.com",
        smtp_password="secret",
        smtp_from="from@example.com",
        smtp_to="to@example.com",
    )

    send_email(settings, "subject", "text body", "<html><body><p>html body</p></body></html>")

    message = recorder.smtp_instance.message
    assert message is not None
    assert message.get_content_type() == "multipart/alternative"
    parts = list(message.iter_parts())
    assert len(parts) == 2
    assert parts[0].get_content_type() == "text/plain"
    assert parts[1].get_content_type() == "text/html"
