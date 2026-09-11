"""受控类别的请求/响应模型（T07）。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.enums import CategoryAction, CategoryStatus


class CategoryCreate(BaseModel):
    """创建类别。"""

    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("类别名称不能为空")
        return cleaned


class CategoryRename(BaseModel):
    """重命名类别。"""

    new_name: str = Field(min_length=1, max_length=200)

    @field_validator("new_name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("类别名称不能为空")
        return cleaned


class CategoryMerge(BaseModel):
    """将当前类别合并到目标类别。"""

    target_category_id: str = Field(min_length=1)


class CategoryRead(BaseModel):
    """类别读取结果。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    status: CategoryStatus
    is_default: bool
    created_at: datetime
    updated_at: datetime


class CategoryListResponse(BaseModel):
    total: int
    items: list[CategoryRead]


class CategoryHistoryRead(BaseModel):
    """类别历史记录。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    category_id: Optional[str] = None
    action: CategoryAction
    old_name: Optional[str] = None
    new_name: Optional[str] = None
    target_category_id: Optional[str] = None
    actor: Optional[str] = None
    note: Optional[str] = None
    created_at: datetime


class PublicCategoryItem(BaseModel):
    """公开分类导航项（plan.md API 3）。"""

    name: str
    article_count: int


class PublicCategoryList(BaseModel):
    """公开分类列表。"""

    categories: list[PublicCategoryItem]
