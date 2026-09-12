"""通知与触达层（T22 起）：邮件发送抽象。

设计要点（对齐 `plan.md` v2 技术栈）：
- 发送方抽象为协议 ``MailSender``，生产用 SMTP，测试/本地用记录型实现，
  **测试中绝不真实发信**；
- ``mail_enabled`` 关闭时只记录不投递（可用于预演与本地开发）。
"""

from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

from app.core.config import Settings


@dataclass
class MailMessage:
    """一封待发送的邮件（HTML 与纯文本双版本）。"""

    to: str
    subject: str
    text_body: str
    html_body: str | None = None


class MailSender(Protocol):
    """邮件发送协议。"""

    def send(self, message: MailMessage) -> None:  # pragma: no cover - 协议声明
        """发送一封邮件；失败时抛出异常由调用方决定是否重试。"""


class RecordingMailSender:
    """记录型发送器：只把邮件留在内存里，用于测试与本地预演。"""

    def __init__(self, *, fail_times: int = 0) -> None:
        self.messages: list[MailMessage] = []
        self.fail_times = fail_times
        self.attempts = 0

    def send(self, message: MailMessage) -> None:
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise RuntimeError("模拟发送失败")
        self.messages.append(message)

    @property
    def last(self) -> MailMessage | None:
        """返回最近一次成功发送的邮件。"""

        return self.messages[-1] if self.messages else None


class SmtpMailSender:
    """SMTP 发送实现（生产）；本地可指向 Mailpit/MailHog 之类的邮件捕获工具。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send(self, message: MailMessage) -> None:
        email = EmailMessage()
        email["From"] = self.settings.mail_from
        email["To"] = message.to
        email["Subject"] = message.subject
        email.set_content(message.text_body)
        if message.html_body:
            email.add_alternative(message.html_body, subtype="html")

        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=15) as client:
            if self.settings.smtp_use_tls:
                client.starttls()
            if self.settings.smtp_user:
                client.login(self.settings.smtp_user, self.settings.smtp_password)
            client.send_message(email)


def build_mail_sender(settings: Settings) -> MailSender:
    """按配置构造发送器：未开启发信时使用记录型实现（不会真的发出邮件）。"""

    if settings.mail_enabled:
        return SmtpMailSender(settings)
    return RecordingMailSender()
