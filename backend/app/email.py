"""Sending transactional email over SMTP."""

import smtplib
from email.message import EmailMessage

from app.config import get_settings


def send_email(to: str, subject: str, body: str) -> None:
    """Send a plain-text email, or do nothing if SMTP isn't configured.

    An empty SMTP host means email is disabled (handy for tests and local
    runs without a mail server); any real sending error propagates to the
    caller, which decides whether it should fail the request.

    STARTTLS and login are optional: dev servers like Mailpit need neither,
    while a production mailbox provider needs both. They switch on only when
    the matching settings are present, so the same code covers both.
    """
    settings = get_settings()
    if not settings.smtp_host:
        return

    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)
