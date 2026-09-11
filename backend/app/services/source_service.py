"""来源/关注领域配置服务（T04）。

本层只负责配置的读写与业务校验，不涉及任何抓取执行逻辑（见 T05）。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.enums import SourceListType
from app.db.models import Source
from app.schemas.source import SourceCreate, SourceUpdate, validate_source_fields


def create_source(session: Session, payload: SourceCreate) -> Source:
    """新增来源（含关注领域、黑白名单归属与权重）。"""

    site_url = str(payload.site_url)
    duplicate = session.scalars(select(Source).where(Source.site_url == site_url)).first()
    if duplicate is not None:
        raise ApiError(409, "CONFLICT", "该站点已存在配置")

    data = payload.model_dump()
    data["site_url"] = site_url
    if data.get("weight") is None:
        # 未指定权重时，与其他来源默认相等
        data["weight"] = 1.0

    source = Source(**data)
    session.add(source)
    session.commit()
    session.refresh(source)
    return source


def list_sources(session: Session, *, list_type: SourceListType | None = None) -> list[Source]:
    """列出来源；可按白名单/黑名单归属过滤。"""

    statement = select(Source).order_by(Source.created_at)
    if list_type is not None:
        statement = statement.where(Source.list_type == list_type)
    return list(session.scalars(statement))


def get_source(session: Session, source_id: str) -> Source:
    """按 ID 读取来源，不存在时抛出 404。"""

    source = session.get(Source, source_id)
    if source is None:
        raise ApiError(404, "NOT_FOUND", "来源不存在")
    return source


def list_public_sources(session: Session) -> list[Source]:
    """公开的来源状态列表（含最后一次成功更新时间，T19）。"""

    statement = select(Source).where(Source.is_active.is_(True)).order_by(Source.name)
    return list(session.scalars(statement))


def update_source(session: Session, source_id: str, payload: SourceUpdate) -> Source:
    """局部更新来源配置，并校验更新后的整体状态仍然合法。"""

    source = get_source(session, source_id)
    changes = payload.model_dump(exclude_unset=True)

    if "site_url" in changes and payload.site_url is not None:
        new_url = str(payload.site_url)
        duplicate = session.scalars(
            select(Source).where(Source.site_url == new_url, Source.id != source_id)
        ).first()
        if duplicate is not None:
            raise ApiError(409, "CONFLICT", "该站点已存在配置")
        changes["site_url"] = new_url

    for field, value in changes.items():
        setattr(source, field, value)

    source.name = validate_source_fields(
        name=source.name,
        list_type=source.list_type,
        focus_area_name=source.focus_area_name,
        focus_area_description=source.focus_area_description,
        keywords=source.keywords or [],
        example_urls=source.example_urls or [],
        weight=source.weight,
    )

    session.commit()
    session.refresh(source)
    return source
