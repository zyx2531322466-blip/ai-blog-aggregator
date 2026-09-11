"""ORM 基类与通用工具。"""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有 ORM 模型的声明式基类。"""


def generate_id(prefix: str) -> str:
    """生成带语义前缀的字符串主键，例如 ``article_3f2a...``。

    使用前缀 + UUID4，既避免自增主键被枚举，也与 `plan.md` 中的
    ``article_123`` / ``source_45`` 形式保持一致。
    """

    return f"{prefix}_{uuid4().hex}"


def utcnow() -> datetime:
    """返回带 UTC 时区的当前时间，统一全站时间基准。"""

    return datetime.now(timezone.utc)
