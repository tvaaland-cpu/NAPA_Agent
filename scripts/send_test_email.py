from __future__ import annotations

from datetime import datetime, timezone
import sys
from pathlib import Path
import argparse
import os




def main() -> None:
    parser = argparse.ArgumentParser(description="Send a test email using NAPA Agent settings")
    parser.add_argument("--insecure", action="store_true", help="Skip TLS certificate verification (testing only)")
    parser.add_argument("--ca-file", type=str, help="Path to CA bundle to trust for SMTP TLS")
    args = parser.parse_args()

    # Ensure project root is on sys.path so `napa_agent` imports work
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))

    # Apply TLS-related CLI options via env vars read by emailer
    if args.insecure:
        os.environ.setdefault("SMTP_INSECURE_SKIP_VERIFY", "1")
    if args.ca_file:
        os.environ.setdefault("SMTP_CA_FILE", args.ca_file)

    # Import app settings and emailer after sys.path adjustments
    from napa_agent.config import get_settings
    from napa_agent.notify.emailer import send_email

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
