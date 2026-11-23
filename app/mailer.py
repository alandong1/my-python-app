"""发送邮件。没配置 SMTP 时只把内容打印到服务器日志，方便本地开发。"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from . import settings

log = logging.getLogger("mailer")


def send_email(to: str, subject: str, body: str) -> None:
    if not settings.SMTP_HOST:
        log.warning("未配置 SMTP，邮件未发送。收件人：%s\n主题：%s\n%s", to, subject, body)
        return
    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as s:
        s.starttls()
        if settings.SMTP_USER:
            s.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        s.send_message(msg)
