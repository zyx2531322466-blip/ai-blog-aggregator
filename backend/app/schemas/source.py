"""来源/关注领域配置的请求与响应模型（T04）。

数据模型说明：按 T02 的表结构，``Source`` 同时承载"站点"与"关注领域定义"
两组字段，因此本模块用同一资源表达 T04 的三项能力：
1. 关注领域配置（focus_area_* + keywords/exclude_keywords/example_urls/...）
2. 站点白名单/黑名单（list_type）
3. 来源权重（weight，未指定时默认 1.0，与其他来源相等）
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from app.db.enums import SourceListType, UpdateFrequency


def validate_source_fields(
    *,
    name: str,
    list_type: SourceListType,
    focus_area_name: str | None,
    focus_area_description: str | None,
    keywords: list[str],
    example_urls: list[str],
    weight: float,
) -> str:
    """校验来源/关注领域字段，返回规整后的名称。

    规则（对应 T04 验收标准）：
    - 名称不可为空白；
    - 白名单来源必须定义完整的关注领域（名称、描述、至少一个关键词、至少一个示例文章）；
    - 权重必须大于 0。
    """

    cleaned_name = (name or "").strip()
    if not cleaned_name:
        raise ValueError("来源名称不能为空")

    if list_type is SourceListType.WHITELIST:
        if not (focus_area_name and focus_area_name.strip()):
            raise ValueError("白名单来源必须提供关注领域名称")
        if not (focus_area_description and focus_area_description.strip()):
            raise ValueError("白名单来源必须提供关注领域描述")
        if not keywords:
            raise ValueError("关注领域至少需要一个关键词")
        if not example_urls:
            raise ValueError("关注领域至少需要一个示例文章链接")

    if weight is None or weight <= 0:
        raise ValueError("来源权重必须大于 0")

    return cleaned_name


class SourceCreate(BaseModel):
    """新增来源/关注领域。"""

    name: str = Field(min_length=1, max_length=200)
    site_url: HttpUrl
    description: Optional[str] = None

    focus_area_name: Optional[str] = Field(default=None, max_length=200)
    focus_area_description: Optional[str] = None
    keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    example_urls: list[str] = Field(default_factory=list)
    counter_example_urls: list[str] = Field(default_factory=list)

    list_type: SourceListType = SourceListType.WHITELIST
    # None 表示"未指定"，落库时统一取 1.0（与其他来源默认权重相等）
    weight: Optional[float] = None

    update_frequency: UpdateFrequency = UpdateFrequency.NORMAL
    update_interval_seconds: Optional[int] = Field(default=None, gt=0)

    @field_validator("site_url", mode="before")
    @classmethod
    def _strip_site_url(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("keywords", "exclude_keywords")
    @classmethod
    def _clean_keywords(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item and item.strip()]

    @field_validator("example_urls", "counter_example_urls")
    @classmethod
    def _validate_url_list(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            candidate = (item or "").strip()
            if not candidate:
                continue
            if not (candidate.startswith("http://") or candidate.startswith("https://")):
                raise ValueError(f"示例/反例链接必须是 http(s) URL: {candidate}")
            cleaned.append(candidate)
        return cleaned

    @model_validator(mode="after")
    def _validate(self) -> "SourceCreate":
        self.name = validate_source_fields(
            name=self.name,
            list_type=self.list_type,
            focus_area_name=self.focus_area_name,
            focus_area_description=self.focus_area_description,
            keywords=self.keywords,
            example_urls=self.example_urls,
            weight=1.0 if self.weight is None else self.weight,
        )
        return self


class SourceUpdate(BaseModel):
    """编辑来源/关注领域（局部更新）。"""

    name: Optional[str] = Field(default=None, max_length=200)
    site_url: Optional[HttpUrl] = None
    description: Optional[str] = None

    focus_area_name: Optional[str] = None
    focus_area_description: Optional[str] = None
    keywords: Optional[list[str]] = None
    exclude_keywords: Optional[list[str]] = None
    example_urls: Optional[list[str]] = None
    counter_example_urls: Optional[list[str]] = None
    list_type: Optional[SourceListType] = None
    weight: Optional[float] = None

    update_frequency: Optional[UpdateFrequency] = None
    update_interval_seconds: Optional[int] = Field(default=None, gt=0)

    @field_validator("keywords", "exclude_keywords")
    @classmethod
    def _clean_keywords(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return [item.strip() for item in value if item and item.strip()]

    @field_validator("example_urls", "counter_example_urls")
    @classmethod
    def _validate_url_list(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned: list[str] = []
        for item in value:
            candidate = (item or "").strip()
            if not candidate:
                continue
            if not (candidate.startswith("http://") or candidate.startswith("https://")):
                raise ValueError(f"示例/反例链接必须是 http(s) URL: {candidate}")
            cleaned.append(candidate)
        return cleaned


class SourceRead(BaseModel):
    """来源/关注领域的读取结果。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    site_url: str
    description: Optional[str] = None

    focus_area_name: Optional[str] = None
    focus_area_description: Optional[str] = None
    keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    example_urls: list[str] = Field(default_factory=list)
    counter_example_urls: list[str] = Field(default_factory=list)

    list_type: SourceListType
    weight: float
    update_frequency: UpdateFrequency
    update_interval_seconds: Optional[int] = None
    is_active: bool

    last_crawled_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class SourceListResponse(BaseModel):
    """来源列表。"""

    total: int
    items: list[SourceRead]


class FrequencyTierRead(BaseModel):
    """建议的更新频率档位（T17）。"""

    frequency: UpdateFrequency
    label: str
    interval_seconds: int


class PublicSourceRead(BaseModel):
    """公开的来源状态（T19）：仅暴露新鲜度相关信息。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    site_url: str
    last_success_at: Optional[datetime] = None
    last_crawled_at: Optional[datetime] = None


class PublicSourceList(BaseModel):
    """公开来源状态列表。"""

    total: int
    items: list[PublicSourceRead]
