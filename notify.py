"""Send the report by email via plain SMTP (works with Gmail, Outlook, etc.)."""

import os
import smtplib
from email.mime.text import MIMEText


def send_email(subject: str, body: str) -> None:
    host = os.environ["SMTP_HOST"]
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASS"]
    to_addr = os.environ["EMAIL_TO"]
    from_addr = os.getenv("EMAIL_FROM", user)

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(from_addr, [to_addr], msg.as_string())
