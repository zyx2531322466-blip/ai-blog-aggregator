"""合并组主记录选择规则（T18）。

优先级（由高到低）：
1. 来源权威权重（``Source.weight``，越大越优先）
2. 发布时间最早
3. 内容完整度（正文越长越优先）
4. 原文可访问性（可访问优先）
5. 标题规范程度（过短/占位标题靠后）

完全并列时按创建时间、再按 ID 兜底，保证结果稳定可复现。
"""

from datetime import timezone

from app.db.models import Article

TITLE_PENALTY_PATTERNS = ("首页", "无标题", "untitled", "404", "导航", "目录")


def title_quality(title: str | None) -> int:
    """标题规范程度评分（越长越规范；命中占位标题扣分）。"""

    cleaned = (title or "").strip()
    score = len(cleaned)
    lowered = cleaned.lower()
    if any(pattern in lowered for pattern in TITLE_PENALTY_PATTERNS):
        score -= 100
    return score


def _timestamp(value) -> float:
    if value is None:
        return float("inf")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _weight(article: Article) -> float:
    if article.source is None or article.source.weight is None:
        return 0.0
    return float(article.source.weight)


def primary_sort_key(article: Article) -> tuple:
    """主记录选择排序键（升序取第一个）。"""

    return (
        -_weight(article),  # 权重越大越优先
        _timestamp(article.published_at),  # 发布时间越早越优先（None 最差）
        -len(article.content or ""),  # 内容越完整越优先
        -int(bool(article.is_accessible)),  # 可访问优先
        -title_quality(article.title),  # 标题越规范越优先
        _timestamp(article.created_at),  # 创建时间越早越优先
        article.id,
    )


def choose_primary(members: list[Article]) -> Article:
    """从合并组成员中按既定优先级选出主记录。

    若组内存在可访问的来源，则只在可访问成员中选择（满足"主记录失效即可切换"）；
    在候选集合内再按"权重 > 发布时间 > 内容完整度 > 标题规范程度"排序。
    """

    if not members:
        raise ValueError("合并组为空，无法选择主记录")

    accessible = [member for member in members if member.is_accessible]
    candidates = accessible or members
    return sorted(candidates, key=primary_sort_key)[0]
