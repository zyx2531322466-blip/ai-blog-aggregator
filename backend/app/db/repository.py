"""通用数据访问基类（Repository）。

后续各业务模块（来源、类别、文章、去重等）在同一会话上复用本基类，
保证数据访问方式一致、可测试。
"""

from typing import Any, Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class Repository(Generic[ModelT]):
    """针对单一 ORM 模型的基础 CRUD 仓储。"""

    def __init__(self, session: Session, model: type[ModelT]) -> None:
        self.session = session
        self.model = model

    def add(self, obj: ModelT) -> ModelT:
        """新增并 flush（由调用方决定何时 commit）。"""

        self.session.add(obj)
        self.session.flush()
        return obj

    def get(self, primary_key: str) -> ModelT | None:
        """按主键读取。"""

        return self.session.get(self.model, primary_key)

    def list(self, **filters: Any) -> list[ModelT]:
        """按等值条件列出记录。"""

        statement = select(self.model)
        for field, value in filters.items():
            statement = statement.where(getattr(self.model, field) == value)
        return list(self.session.scalars(statement))

    def delete(self, obj: ModelT) -> None:
        """删除记录并 flush。"""

        self.session.delete(obj)
        self.session.flush()

    def commit(self) -> None:
        """提交当前事务。"""

        self.session.commit()
