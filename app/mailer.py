import smtplib
from email.message import EmailMessage

from flask import current_app


def send_email(to, subject, body):
    """Send one email. Returns 'sent', 'not_configured' or 'failed'."""
    config = current_app.config
    if config.get("MAIL_SENDER"):  # Replaced in tests.
        return config["MAIL_SENDER"](to, subject, body)
    if not config["SMTP_HOST"]:
        return "not_configured"
    message = EmailMessage()
    message["From"] = config["SMTP_FROM"] or config["SMTP_USER"]
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP(config["SMTP_HOST"], config["SMTP_PORT"], timeout=15) as smtp:
            smtp.starttls()
            if config["SMTP_USER"]:
                smtp.login(config["SMTP_USER"], config["SMTP_PASSWORD"])
            smtp.send_message(message)
        return "sent"
    except (OSError, smtplib.SMTPException) as error:
        current_app.logger.warning("Email failed: %s", type(error).__name__)
        return "failed"
