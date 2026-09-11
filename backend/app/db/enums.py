"""存储层使用的枚举类型。

枚举值统一使用稳定的英文小写字符串（写入数据库），
中文展示文案由展示层负责映射，避免把界面文案固化进数据结构。
"""

import enum


class ArticleStatus(str, enum.Enum):
    """文章处理状态。"""

    PENDING = "pending"  # 待分类（解析完成、尚未分类）
    NORMAL = "normal"  # 正常（已分类）
    UNCATEGORIZED = "uncategorized"  # 未分类（归属兜底类别）
    ERROR = "error"  # 异常（解析失败等）
    FILTERED = "filtered"  # 已过滤（低质量/不相关内容）


class CategoryStatus(str, enum.Enum):
    """类别启用状态。"""

    ACTIVE = "active"
    INACTIVE = "inactive"


class CategoryAction(str, enum.Enum):
    """类别历史动作。"""

    CREATE = "create"
    RENAME = "rename"
    MERGE = "merge"
    DEACTIVATE = "deactivate"
    ACTIVATE = "activate"


class SourceListType(str, enum.Enum):
    """站点在采集范围中的黑白名单归属。"""

    WHITELIST = "whitelist"  # 允许抓取
    BLACKLIST = "blacklist"  # 禁止抓取
    NEUTRAL = "neutral"  # 未表态（默认不抓取）


class UpdateFrequency(str, enum.Enum):
    """来源级更新频率档位（T17）。

    HIGH / NORMAL / LOW 为建议档位；CUSTOM 表示使用
    ``Source.update_interval_seconds`` 自定义间隔。
    """

    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"
    CUSTOM = "custom"


class DedupRelationType(str, enum.Enum):
    """去重关系类型。"""

    EXACT_DUPLICATE = "exact_duplicate"  # 完全重复：强制合并
    NEAR_DUPLICATE = "near_duplicate"  # 近重复：阈值可配置合并
    RELATED = "related"  # 不同视角：不合并，仅关联推荐


class CrawlStatus(str, enum.Enum):
    """抓取结果状态（T05）。"""

    FETCHED = "fetched"  # 抓取成功并保存原始 HTML
    FAILED = "failed"  # 抓取失败（网络/超时等）
    ROBOTS_DENIED = "robots_denied"  # 被目标站 robots.txt 拒绝
    SKIPPED = "skipped"  # 被跳过（如黑名单站点）
