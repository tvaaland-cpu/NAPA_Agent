from __future__ import annotations

import smtplib
import ssl
import os
import warnings
from email.message import EmailMessage
from pathlib import Path
from typing import TYPE_CHECKING

import certifi

if TYPE_CHECKING:
    from napa_agent.config import Settings


def _tls_context() -> ssl.SSLContext:
    # Allow opting out of certificate verification for testing via env var
    if os.getenv("SMTP_INSECURE_SKIP_VERIFY"):
        warnings.warn(
            "SMTP_INSECURE_SKIP_VERIFY is set: TLS certificate verification is disabled",
        )
        return ssl._create_unverified_context()

    # Allow specifying an alternate CA bundle via env var (useful for corporate proxies)
    ca_file = os.getenv("SMTP_CA_FILE")
    if ca_file:
        ca_path = Path(ca_file)
        if ca_path.exists():
            return ssl.create_default_context(cafile=str(ca_path))
        warnings.warn(f"SMTP_CA_FILE is set but path not found: {ca_file}")

    # Default: Use certifi CA bundle to avoid Windows/Python trust-store issues
    return ssl.create_default_context(cafile=certifi.where())


def send_email(settings: Settings, subject: str, body: str, html_body: str | None = None) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = settings.smtp_to
    message.set_content(body)
    
    # If HTML body is provided, add it as an alternative
    if html_body:
        message.add_alternative(html_body, subtype="html")

    port = int(settings.smtp_port)
    tls_context = _tls_context()

    try:
        # Port 465: implicit TLS
        if port == 465:
            with smtplib.SMTP_SSL(
                settings.smtp_host,
                port,
                timeout=30,
                context=tls_context,
            ) as smtp:
                smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(message)
            return

        # Port 587 (or others): STARTTLS
        with smtplib.SMTP(settings.smtp_host, port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls(context=tls_context)
            smtp.ehlo()
            smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
    except ssl.SSLCertVerificationError as exc:
        # Re-raise with an actionable message to help debugging TLS issues.
        raise RuntimeError(
            "SMTP TLS certificate verification failed. If you're behind a proxy or using a private CA, "
            "set the SMTP_CA_FILE environment variable to point to a CA bundle, or run the test with "
            "SMTP_INSECURE_SKIP_VERIFY=1 (insecure, testing only). Original error: "
            + str(exc)
        ) from exc
