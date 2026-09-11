"""公开来源状态接口（T19：来源维度展示最后更新时间，匿名访问）。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.source import PublicSourceList, PublicSourceRead
from app.services import source_service

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=PublicSourceList)
def list_sources(session: Session = Depends(get_db)) -> PublicSourceList:
    """返回启用来源的最后成功更新时间/最后抓取时间。"""

    sources = source_service.list_public_sources(session)
    return PublicSourceList(
        total=len(sources),
        items=[PublicSourceRead.model_validate(source) for source in sources],
    )
