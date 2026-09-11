"""内容质量过滤实现（T16）。"""

from dataclasses import dataclass

from bs4 import BeautifulSoup

MIN_CONTENT_LENGTH = 10
MIN_LINK_TEXT_RATIO = 0.5

# 典型广告/营销用语：命中多个即判为广告页
AD_PATTERNS = (
    "立即购买",
    "点击购买",
    "限时优惠",
    "扫码关注",
    "加微信",
    "点击咨询",
    "立即下载",
    "领取优惠",
)
# 典型导航/占位页标题
NAV_TITLE_PATTERNS = ("首页", "导航", "目录", "404", "页面不存在", "站点地图")


@dataclass(frozen=True)
class QualityDecision:
    """过滤判定结果。"""

    filtered: bool
    reason: str | None = None


def evaluate_quality(
    *,
    title: str,
    content: str,
    raw_html: str | None = None,
    exclude_keywords: tuple[str, ...] | list[str] = (),
) -> QualityDecision:
    """判断内容是否属于低质量/不相关内容。"""

    cleaned = (content or "").strip()
    haystack = f"{title or ''}\n{cleaned}".lower()

    if len(cleaned) < MIN_CONTENT_LENGTH:
        return QualityDecision(True, "内容过短，疑似非文章页")

    # 1) 来源配置的排除词优先
    hits = [keyword for keyword in exclude_keywords if keyword and keyword.lower() in haystack]
    if hits:
        return QualityDecision(True, f"命中排除词: {'、'.join(hits)}")

    # 2) 导航/占位页标题
    if len(cleaned) < 200 and any(pattern.lower() in haystack for pattern in NAV_TITLE_PATTERNS):
        return QualityDecision(True, "疑似导航/占位页")

    # 3) 广告/营销内容
    ad_hits = [pattern for pattern in AD_PATTERNS if pattern in cleaned]
    if len(ad_hits) >= 2:
        return QualityDecision(True, f"疑似广告页: {'、'.join(ad_hits)}")

    # 4) 链接密度过高（纯导航/聚合页）
    if raw_html and link_text_ratio(raw_html) >= MIN_LINK_TEXT_RATIO:
        return QualityDecision(True, "链接密度过高，疑似导航/聚合页")

    return QualityDecision(False)


def link_text_ratio(html: str) -> float:
    """计算链接文本占页面文本的比例。"""

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    total_text = len(soup.get_text(" ", strip=True))
    if total_text == 0:
        return 1.0
    link_text = sum(len(anchor.get_text(" ", strip=True)) for anchor in soup.find_all("a"))
    return link_text / total_text
