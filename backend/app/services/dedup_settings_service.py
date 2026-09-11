"""去重策略配置、审计与回滚服务（T13 / T15）。

阈值默认取保守方向（"误合并比漏合并更严重"），即需要更强的相似证据才判定近重复。
每次变更都会写入 ``dedup_setting_history``，记录"谁在何时把值从多少改为多少"。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models import DedupSetting, DedupSettingHistory

NEAR_DUPLICATE_THRESHOLD_KEY = "near_duplicate_threshold"
# 保守默认：相似度需达到 0.90 才判定为近重复
DEFAULT_NEAR_DUPLICATE_THRESHOLD = 0.90


def get_near_duplicate_threshold(session: Session) -> float:
    """读取近重复判定阈值（未配置时使用保守默认值）。"""

    setting = session.get(DedupSetting, NEAR_DUPLICATE_THRESHOLD_KEY)
    if setting is None:
        return DEFAULT_NEAR_DUPLICATE_THRESHOLD
    try:
        return float(setting.value)
    except (TypeError, ValueError):
        return DEFAULT_NEAR_DUPLICATE_THRESHOLD


def set_near_duplicate_threshold(session: Session, value: float, *, actor: str = "system") -> float:
    """设置近重复判定阈值，并记录一条变更历史。"""

    if not 0.0 <= value <= 1.0:
        raise ApiError(422, "VALIDATION_ERROR", "阈值必须位于 0 到 1 之间")

    previous = get_near_duplicate_threshold(session)
    setting = session.get(DedupSetting, NEAR_DUPLICATE_THRESHOLD_KEY)
    if setting is None:
        setting = DedupSetting(key=NEAR_DUPLICATE_THRESHOLD_KEY, value=str(value))
        session.add(setting)
    else:
        setting.value = str(value)

    session.add(
        DedupSettingHistory(
            key=NEAR_DUPLICATE_THRESHOLD_KEY,
            old_value=str(previous),
            new_value=str(value),
            actor=actor,
        )
    )
    session.commit()
    return value


def get_setting_history(session: Session) -> list[DedupSettingHistory]:
    """按时间顺序返回阈值变更记录。"""

    statement = (
        select(DedupSettingHistory)
        .where(DedupSettingHistory.key == NEAR_DUPLICATE_THRESHOLD_KEY)
        .order_by(DedupSettingHistory.created_at, DedupSettingHistory.id)
    )
    return list(session.scalars(statement))


def rollback_setting(session: Session, history_id: str, *, actor: str = "system") -> float:
    """回滚某次阈值变更（恢复为该次变更前的值），并记录一条新的变更历史。"""

    record = session.get(DedupSettingHistory, history_id)
    if record is None or record.key != NEAR_DUPLICATE_THRESHOLD_KEY:
        raise ApiError(404, "NOT_FOUND", "变更记录不存在")

    target = (
        float(record.old_value)
        if record.old_value not in (None, "")
        else DEFAULT_NEAR_DUPLICATE_THRESHOLD
    )
    return set_near_duplicate_threshold(session, target, actor=actor)
