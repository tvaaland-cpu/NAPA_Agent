from __future__ import annotations

from datetime import datetime, timezone

from napa_agent.config import get_settings
from napa_agent.notify.emailer import send_email


def main() -> None:
    settings = get_settings()
    sent_at = datetime.now(timezone.utc).isoformat()
    subject = "NAPA Agent SMTP test"
    body = (
        "This is a test email sent by NAPA Agent.\n\n"
        f"Sent at (UTC): {sent_at}\n"
        f"SMTP host: {settings.smtp_host}\n"
        f"SMTP port: {settings.smtp_port}\n"
    )
    send_email(settings, subject, body)
    print("Test email sent successfully.")


if __name__ == "__main__":
    main()
