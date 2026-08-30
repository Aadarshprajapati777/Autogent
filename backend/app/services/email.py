"""Email service. Uses SMTP if configured; otherwise logs (dev mode)."""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from ..config import settings

log = logging.getLogger(__name__)


def _send(to: str, subject: str, body: str) -> None:
    if not settings.smtp_host:
        log.info("[dev email] to=%s subject=%s body=%s", to, subject, body[:200])
        return
    msg = MIMEMultipart("alternative")
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_username:
            server.starttls()
            server.login(settings.smtp_username, settings.smtp_password)
        server.sendmail(settings.smtp_from, [to], msg.as_string())


def send_welcome_email(to: str, name: str) -> None:
    _send(to, "Welcome to Autogent", f"Hi {name},\n\nWelcome to Autogent!")


def send_password_reset_email(to: str, name: str, reset_link: str) -> None:
    _send(
        to, "Reset your Autogent password",
        f"Hi {name},\n\nReset your password: {reset_link}\n\nThis link expires in 1 hour.",
    )


def send_email(to: str, subject: str, body: str) -> None:
    _send(to, subject, body)
