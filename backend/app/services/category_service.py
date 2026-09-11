"""受控类别管理服务（T07）。

分类体系由维护者管理：支持创建、重命名、合并、停用/启用，
并保留完整的操作历史（`category_history`）。
"""

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.enums import CategoryAction, CategoryStatus
from app.db.models import Article, Category, CategoryHistory

# 初始类别清单（T07 默认基线，维护者可随时调整）
DEFAULT_CATEGORIES: tuple[str, ...] = (
    "AI/机器学习",
    "Web 开发",
    "数据库",
    "运维",
    "安全",
    "产品设计",
    "其他",
)

# 无法分类时的兜底类别（T12 使用）
FALLBACK_CATEGORY_NAME = "其他"


def ensure_default_categories(session: Session) -> list[Category]:
    """首次启动时预置默认类别；已存在任何类别时不再重复预置。"""

    existing_count = session.scalar(select(func.count()).select_from(Category)) or 0
    if existing_count == 0:
        for name in DEFAULT_CATEGORIES:
            category = Category(name=name, is_default=True, status=CategoryStatus.ACTIVE)
            session.add(category)
            session.flush()
            session.add(
                CategoryHistory(
                    category_id=category.id,
                    action=CategoryAction.CREATE,
                    new_name=name,
                    actor="system",
                    note="系统初始化默认类别",
                )
            )
        session.commit()

    return list(session.scalars(select(Category).order_by(Category.created_at)))


def list_categories(session: Session, *, include_inactive: bool = True) -> list[Category]:
    """列出类别；``include_inactive=False`` 时仅返回启用中的类别。"""

    statement = select(Category).order_by(Category.created_at)
    if not include_inactive:
        statement = statement.where(Category.status == CategoryStatus.ACTIVE)
    return list(session.scalars(statement))


def get_category(session: Session, category_id: str) -> Category:
    """按 ID 读取类别，不存在抛出 404。"""

    category = session.get(Category, category_id)
    if category is None:
        raise ApiError(404, "NOT_FOUND", "类别不存在")
    return category


def find_category_by_name(session: Session, name: str) -> Category | None:
    return session.scalars(select(Category).where(Category.name == name)).first()


def create_category(session: Session, name: str, *, actor: str) -> Category:
    """创建新类别。"""

    _ensure_name_available(session, name)
    category = Category(name=name, is_default=False, status=CategoryStatus.ACTIVE)
    session.add(category)
    session.flush()
    session.add(
        CategoryHistory(
            category_id=category.id,
            action=CategoryAction.CREATE,
            new_name=name,
            actor=actor,
        )
    )
    session.commit()
    session.refresh(category)
    return category


def rename_category(session: Session, category_id: str, new_name: str, *, actor: str) -> Category:
    """重命名类别（默认类别亦可重命名）。"""

    category = get_category(session, category_id)
    _ensure_name_available(session, new_name, exclude_id=category_id)
    old_name = category.name
    category.name = new_name
    session.add(
        CategoryHistory(
            category_id=category.id,
            action=CategoryAction.RENAME,
            old_name=old_name,
            new_name=new_name,
            actor=actor,
        )
    )
    session.commit()
    session.refresh(category)
    return category


def merge_categories(session: Session, source_id: str, target_id: str, *, actor: str) -> Category:
    """将 ``source_id`` 合并到 ``target_id``，原类别下文章归入目标类别。"""

    if source_id == target_id:
        raise ApiError(422, "VALIDATION_ERROR", "不能将类别合并到自身")

    source = get_category(session, source_id)
    target = get_category(session, target_id)

    session.execute(
        update(Article)
        .where(Article.primary_category_id == source.id)
        .values(primary_category_id=target.id)
    )
    session.add(
        CategoryHistory(
            category_id=source.id,
            action=CategoryAction.MERGE,
            old_name=source.name,
            new_name=target.name,
            target_category_id=target.id,
            actor=actor,
        )
    )
    session.flush()
    source.status = CategoryStatus.INACTIVE
    session.commit()
    session.refresh(target)
    return target


def set_category_status(
    session: Session, category_id: str, status: CategoryStatus, *, actor: str
) -> Category:
    """停用或启用类别；已归类文章的历史记录不受影响。"""

    category = get_category(session, category_id)
    category.status = status
    session.add(
        CategoryHistory(
            category_id=category.id,
            action=(
                CategoryAction.DEACTIVATE
                if status is CategoryStatus.INACTIVE
                else CategoryAction.ACTIVATE
            ),
            old_name=category.name,
            new_name=category.name,
            actor=actor,
        )
    )
    session.commit()
    session.refresh(category)
    return category


def get_category_history(session: Session, category_id: str) -> list[CategoryHistory]:
    """读取某类别的操作历史（时间正序）。"""

    get_category(session, category_id)
    statement = (
        select(CategoryHistory)
        .where(CategoryHistory.category_id == category_id)
        .order_by(CategoryHistory.created_at)
    )
    return list(session.scalars(statement))


def _ensure_name_available(session: Session, name: str, *, exclude_id: str | None = None) -> None:
    existing = find_category_by_name(session, name)
    if existing is not None and existing.id != exclude_id:
        raise ApiError(409, "CONFLICT", "已存在同名类别")
