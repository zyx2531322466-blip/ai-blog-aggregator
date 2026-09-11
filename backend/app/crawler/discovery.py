"""从站点页面中发现候选文章链接。

发现策略（T05 + T22 内容质量修复）：
- 取页面中指向同域的链接（可关闭），去锚点、去重、保序；
- 默认按"文章特征"打分排序，再取前 ``limit`` 个，
  避免站点首页把"关于/标签/登录"等导航链接排在真正文章之前；
- ``prefer_articles=False`` 时退化为纯文档顺序（保留旧行为，便于对照与测试）。
"""

import re
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

_IGNORED_PREFIXES = ("#", "mailto:", "javascript:", "tel:")

# URL 中出现日期段，通常是文章详情页
_DATE_PATTERN = re.compile(r"/(?:19|20)\d{2}(?:[/-]\d{1,2})?(?:[/-]\d{1,2})?")
# 常见的文章路径片段
_ARTICLE_SEGMENTS = frozenset(
    {
        "article",
        "articles",
        "post",
        "posts",
        "archives",
        "archive",
        "news",
        "story",
        "stories",
        "blog",
        "p",
        "entry",
        "entries",
    }
)
# 常见的栏目/功能页路径片段（降权）
_NAV_SEGMENTS = frozenset(
    {
        "about",
        "contact",
        "guestbook",
        "plugins",
        "featured",
        "feed",
        "rss",
        "login",
        "signin",
        "signup",
        "register",
        "search",
        "tag",
        "tags",
        "category",
        "categories",
        "author",
        "authors",
        "page",
        "privacy",
        "terms",
        "advertise",
        "subscribe",
        "donate",
        "comment",
        "comments",
        "help",
        "faq",
        "sitemap",
        "index",
        "home",
        "blogroll",
        "links",
        "friends",
    }
)
# 无信息量的锚文本（降权）
_GENERIC_ANCHORS = frozenset(
    {
        "更多",
        "更多内容",
        "阅读更多",
        "阅读全文",
        "详情",
        "点击查看",
        "首页",
        "关于",
        "关于我",
        "联系",
        "登录",
        "注册",
        "归档",
        "目录",
        "more",
        "read more",
        "home",
        "about",
        "contact",
        "login",
        "next",
        "previous",
    }
)

# 候选收集上限倍数：先多收集再排序，避免"文档顺序前 N 个"限制排序效果
_COLLECT_MULTIPLIER = 5


def article_url_score(url: str, anchor_text: str = "") -> int:
    """给候选链接打"像不像文章详情页"的分，分数越高越可能是文章。"""

    parsed = urlparse(url)
    path = (parsed.path or "/").lower()
    segments = [segment for segment in path.split("/") if segment]
    text = (anchor_text or "").strip()
    lowered_text = text.lower()

    score = 0
    if _DATE_PATTERN.search(path):
        score += 3
    if any(segment in _ARTICLE_SEGMENTS for segment in segments):
        score += 3
    if path.endswith((".html", ".htm", ".shtml")):
        score += 2
    if len(text) >= 8:
        score += 2
    elif 0 < len(text) <= 3:
        score -= 2
    if lowered_text in _GENERIC_ANCHORS:
        score -= 3
    if len(segments) >= 2:
        score += 1
    if any(segment in _NAV_SEGMENTS for segment in segments):
        score -= 3
    return score


def discover_article_urls(
    html: str,
    base_url: str,
    *,
    same_domain: bool = True,
    limit: int = 20,
    prefer_articles: bool = True,
) -> list[str]:
    """提取页面中指向同域内容的候选链接（去重、去锚点）。"""

    soup = BeautifulSoup(html, "lxml")
    base_domain = urlparse(base_url).netloc
    discovered: list[str] = []
    anchor_texts: dict[str, str] = {}
    seen: set[str] = set()
    collect_cap = limit * _COLLECT_MULTIPLIER if prefer_articles else limit

    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        if not href or href.startswith(_IGNORED_PREFIXES):
            continue
        absolute, _ = urldefrag(urljoin(base_url, href))
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue
        if same_domain and parsed.netloc != base_domain:
            continue
        if absolute == base_url or absolute in seen:
            continue
        seen.add(absolute)
        discovered.append(absolute)
        anchor_texts[absolute] = anchor.get_text(" ", strip=True)
        if len(discovered) >= collect_cap:
            break

    if prefer_articles and discovered:
        document_order = {url: index for index, url in enumerate(discovered)}
        discovered.sort(
            key=lambda url: (
                -article_url_score(url, anchor_texts.get(url, "")),
                document_order[url],
            )
        )

    return discovered[:limit]
