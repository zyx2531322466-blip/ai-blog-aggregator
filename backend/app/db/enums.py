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
    KNOWLEDGE_DUPLICATE = "knowledge_duplicate"  # 知识已覆盖（T26 归档，不进列表与推送）


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


# ---------------------------------------------------------------------------
# v2 新增枚举（T22–T26）：订阅推送与知识级去重
# ---------------------------------------------------------------------------


class SubscriptionStatus(str, enum.Enum):
    """匿名订阅状态（T22）：未确认前不产生任何推送。"""

    PENDING_CONFIRMATION = "pending_confirmation"  # 待邮箱确认
    CONFIRMED = "confirmed"  # 已确认，可被推送
    UNSUBSCRIBED = "unsubscribed"  # 已退订


class SubscriptionFrequency(str, enum.Enum):
    """推送节奏（T22）。"""

    DAILY = "daily"
    WEEKLY = "weekly"


class SubscriptionTopicType(str, enum.Enum):
    """订阅方向维度（T22）。"""

    CATEGORY = "category"
    TAG = "tag"
    SOURCE = "source"
    KEYWORD = "keyword"


class DigestStatus(str, enum.Enum):
    """推送记录状态（T23）。"""

    PENDING = "pending"  # 已生成未投递
    SENT = "sent"  # 投递成功
    FAILED = "failed"  # 投递失败（超过重试上限）
    SKIPPED_EMPTY = "skipped_empty"  # 本期无新增，按配置跳过


class KnowledgeStatus(str, enum.Enum):
    """文章的知识级状态（T26）。"""

    NEW = "new"  # 全新知识
    PARTIAL = "partial"  # 部分新增（含已覆盖知识点 + 新增点）
    COVERED = "covered"  # 知识已被覆盖（归档）
    PENDING = "pending"  # 待判定（外部模型暂不可用）


class KnowledgeDecisionType(str, enum.Enum):
    """知识判定结论（T26）。"""

    NEW = "new_knowledge"
    PARTIAL = "partial"
    COVERED = "covered"
    PENDING = "pending"


class WikiEntryStatus(str, enum.Enum):
    """知识 Wiki 条目状态（T25）。"""

    ACTIVE = "active"  # 参与覆盖判定
    RETIRED = "retired"  # 已废止，不再作为覆盖依据
    MERGED = "merged"  # 已合并到其他条目


class WikiEntrySourceType(str, enum.Enum):
    """Wiki 条目来源（T25）。"""

    LLM = "llm"
    HUMAN = "human"


class DecisionActor(str, enum.Enum):
    """判定执行者（T26）：人工结论优先于系统结论。"""

    SYSTEM = "system"
    HUMAN = "human"


class ExtractionStatus(str, enum.Enum):
    """知识点提炼状态（T25）：ok 表示可用于覆盖判定，其他状态会被后续轮次重试。"""

    PENDING = "pending"  # 排队中（尚未调用）
    OK = "ok"  # 提炼成功（结果已缓存）
    FAILED = "failed"  # 调用失败（超时/限流/非法输出），留待重试
