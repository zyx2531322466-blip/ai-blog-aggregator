"""推送全局设置、送达健康与合规自检服务（T24）。

沿用既有 ``dedup_settings`` 的键值模式：
- 配置项落在 ``notification_settings``，每次变更写入 ``notification_setting_history``（谁、何时、从多少到多少）；
- 维护者可在运行时调整节奏、发送时间窗、单封上限、空周期策略与重试上限；
- 退信/失败比例超过阈值时**自动暂停**推送，并留下"系统暂停"的变更记录。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.db.enums import DigestStatus
from app.db.models import Digest, NotificationSetting, NotificationSettingHistory

DEFAULT_FREQUENCY_KEY = "default_frequency"
MAX_ITEMS_KEY = "max_items_per_digest"
WINDOW_START_KEY = "send_window_start_hour"
WINDOW_END_KEY = "send_window_end_hour"
SEND_EMPTY_KEY = "send_empty_digest"
MAX_RETRIES_KEY = "max_retries"
PAUSED_KEY = "sends_paused"
BOUNCE_THRESHOLD_KEY = "bounce_pause_threshold"

ALL_KEYS = (
    DEFAULT_FREQUENCY_KEY,
    MAX_ITEMS_KEY,
    WINDOW_START_KEY,
    WINDOW_END_KEY,
    SEND_EMPTY_KEY,
    MAX_RETRIES_KEY,
    PAUSED_KEY,
    BOUNCE_THRESHOLD_KEY,
)
# 送达健康评估的窗口：最近多少条推送记录
HEALTH_SAMPLE_SIZE = 50


@dataclass
class NotificationSettings:
    """推送全局设置（缺省值来自应用配置）。"""

    default_frequency: str
    max_items_per_digest: int
    send_window_start_hour: int
    send_window_end_hour: int
    send_empty_digest: bool
    max_retries: int
    sends_paused: bool
    bounce_pause_threshold: float


@dataclass
class DeliveryHealth:
    """送达健康与合规自检结果。"""

    sampled: int
    sent: int
    failed: int
    skipped_empty: int
    failure_rate: float
    threshold: float
    paused: bool
    checklist: list[dict[str, Any]]


def _bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _defaults(settings: Settings) -> dict[str, str]:
    return {
        DEFAULT_FREQUENCY_KEY: settings.digest_default_frequency,
        MAX_ITEMS_KEY: str(settings.digest_max_items),
        WINDOW_START_KEY: str(settings.digest_send_window_start_hour),
        WINDOW_END_KEY: str(settings.digest_send_window_end_hour),
        SEND_EMPTY_KEY: "true" if settings.digest_send_empty else "false",
        MAX_RETRIES_KEY: str(settings.digest_max_retries),
        PAUSED_KEY: "false",
        BOUNCE_THRESHOLD_KEY: str(settings.bounce_pause_threshold),
    }


def raw_settings(session: Session, settings: Settings | None = None) -> dict[str, str]:
    """读取原始键值（未配置的项回退到应用配置默认值）。"""

    resolved = _defaults(settings or get_settings())
    for row in session.scalars(select(NotificationSetting)).all():
        resolved[row.key] = row.value
    return resolved


def get_notification_settings(
    session: Session, settings: Settings | None = None
) -> NotificationSettings:
    """读取推送设置（已做类型转换）。"""

    raw = raw_settings(session, settings)
    return NotificationSettings(
        default_frequency=raw[DEFAULT_FREQUENCY_KEY],
        max_items_per_digest=int(raw[MAX_ITEMS_KEY]),
        send_window_start_hour=int(raw[WINDOW_START_KEY]),
        send_window_end_hour=int(raw[WINDOW_END_KEY]),
        send_empty_digest=_bool(raw[SEND_EMPTY_KEY]),
        max_retries=int(raw[MAX_RETRIES_KEY]),
        sends_paused=_bool(raw[PAUSED_KEY]),
        bounce_pause_threshold=float(raw[BOUNCE_THRESHOLD_KEY]),
    )


def effective_app_settings(session: Session, settings: Settings | None = None) -> Settings:
    """把数据库中的设置叠加到应用配置上，供推送流程直接使用。"""

    base = settings or get_settings()
    config = get_notification_settings(session, base)
    return base.model_copy(
        update={
            "digest_default_frequency": config.default_frequency,
            "digest_max_items": config.max_items_per_digest,
            "digest_send_empty": config.send_empty_digest,
            "digest_max_retries": config.max_retries,
            "digest_send_window_start_hour": config.send_window_start_hour,
            "digest_send_window_end_hour": config.send_window_end_hour,
        }
    )


def _validate(key: str, value: Any) -> str:
    """校验并规范化为字符串，非法值抛统一错误。"""

    if key == DEFAULT_FREQUENCY_KEY:
        if str(value) not in {"daily", "weekly"}:
            raise ApiError(400, "VALIDATION_ERROR", "默认节奏只支持 daily 或 weekly")
        return str(value)
    if key == MAX_ITEMS_KEY:
        number = int(value)
        if not 1 <= number <= 50:
            raise ApiError(400, "VALIDATION_ERROR", "单封邮件条数上限必须位于 1 到 50 之间")
        return str(number)
    if key in {WINDOW_START_KEY, WINDOW_END_KEY}:
        number = int(value)
        if not 0 <= number <= 24:
            raise ApiError(400, "VALIDATION_ERROR", "发送时间窗必须位于 0 到 24 点之间")
        return str(number)
    if key in {SEND_EMPTY_KEY, PAUSED_KEY}:
        return "true" if (value is True or _bool(str(value))) else "false"
    if key == MAX_RETRIES_KEY:
        number = int(value)
        if not 0 <= number <= 10:
            raise ApiError(400, "VALIDATION_ERROR", "重试上限必须位于 0 到 10 之间")
        return str(number)
    if key == BOUNCE_THRESHOLD_KEY:
        ratio = float(value)
        if not 0.0 <= ratio <= 1.0:
            raise ApiError(400, "VALIDATION_ERROR", "退信阈值必须位于 0 到 1 之间")
        return str(ratio)
    raise ApiError(400, "VALIDATION_ERROR", f"不支持的配置项：{key}")  # pragma: no cover


def update_notification_settings(
    session: Session,
    changes: dict[str, Any],
    *,
    actor: str = "system",
    settings: Settings | None = None,
) -> NotificationSettings:
    """更新推送设置并记录变更历史；返回更新后的设置。"""

    base = settings or get_settings()
    current = raw_settings(session, base)
    applied: dict[str, str] = {}
    for key, value in changes.items():
        if value is None or key not in ALL_KEYS:
            continue
        applied[key] = _validate(key, value)

    if WINDOW_START_KEY in applied or WINDOW_END_KEY in applied:
        start = int(applied.get(WINDOW_START_KEY, current[WINDOW_START_KEY]))
        end = int(applied.get(WINDOW_END_KEY, current[WINDOW_END_KEY]))
        if start >= end:
            raise ApiError(400, "VALIDATION_ERROR", "发送时间窗的开始时间必须早于结束时间")

    for key, new_value in applied.items():
        old_value = current[key]
        if old_value == new_value:
            continue
        row = session.get(NotificationSetting, key)
        if row is None:
            session.add(NotificationSetting(key=key, value=new_value))
        else:
            row.value = new_value
        session.add(
            NotificationSettingHistory(
                key=key, old_value=old_value, new_value=new_value, actor=actor
            )
        )
    session.commit()
    return get_notification_settings(session, base)


def get_setting_history(session: Session) -> list[NotificationSettingHistory]:
    """按时间倒序返回设置变更历史。"""

    statement = select(NotificationSettingHistory).order_by(
        NotificationSettingHistory.created_at.desc()
    )
    return list(session.scalars(statement).all())


def in_send_window(config: NotificationSettings, now: datetime) -> bool:
    """是否处于允许发送的时间窗内（窗口外顺延，避免深夜打扰）。"""

    if config.send_window_start_hour == config.send_window_end_hour:
        return True  # 起止相同视为"全天可发"
    return config.send_window_start_hour <= now.hour < config.send_window_end_hour


def evaluate_delivery_health(
    session: Session,
    config: NotificationSettings | None = None,
    *,
    settings: Settings | None = None,
    clock: datetime | None = None,
) -> DeliveryHealth:
    """评估最近推送的送达情况，并在失败率超阈值时自动暂停推送。"""

    base = settings or get_settings()
    config = config or get_notification_settings(session, base)
    rows = session.scalars(
        select(Digest).order_by(Digest.created_at.desc()).limit(HEALTH_SAMPLE_SIZE)
    ).all()
    sent = sum(1 for row in rows if row.status is DigestStatus.SENT)
    failed = sum(1 for row in rows if row.status is DigestStatus.FAILED)
    skipped = sum(1 for row in rows if row.status is DigestStatus.SKIPPED_EMPTY)
    attempts = sent + failed
    failure_rate = (failed / attempts) if attempts else 0.0

    paused = config.sends_paused
    if attempts and failure_rate >= config.bounce_pause_threshold and not paused:
        update_notification_settings(
            session,
            {PAUSED_KEY: True},
            actor="system",
            settings=base,
        )
        paused = True

    checklist: list[dict[str, Any]] = [
        {
            "item": "真实发信开关",
            "ok": base.mail_enabled,
            "detail": "已开启" if base.mail_enabled else "当前为预演模式（只记录不投递）",
        },
        {
            "item": "发件人地址",
            "ok": bool(base.mail_from) and "example.com" not in base.mail_from,
            "detail": base.mail_from,
        },
        {
            "item": "退订链接可达性",
            "ok": "localhost" not in base.public_base_url,
            "detail": (
                f"站点地址 {base.public_base_url}"
                + (
                    ""
                    if "localhost" not in base.public_base_url
                    else "（本地地址，订阅者无法访问）"
                )
            ),
        },
        {
            "item": "发信域名认证（SPF/DKIM/DMARC）",
            "ok": False,
            "detail": "需在域名侧配置后手动确认；未配置时邮件可能被判为垃圾邮件",
        },
        {
            "item": "失败率",
            "ok": failure_rate < config.bounce_pause_threshold,
            "detail": f"最近 {attempts} 次投递失败 {failed} 次（{failure_rate:.0%}）",
        },
    ]
    return DeliveryHealth(
        sampled=len(rows),
        sent=sent,
        failed=failed,
        skipped_empty=skipped,
        failure_rate=failure_rate,
        threshold=config.bounce_pause_threshold,
        paused=paused,
        checklist=checklist,
    )
