"""从站点页面中发现候选文章链接。"""

from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

_IGNORED_PREFIXES = ("#", "mailto:", "javascript:", "tel:")


def discover_article_urls(
    html: str,
    base_url: str,
    *,
    same_domain: bool = True,
    limit: int = 20,
) -> list[str]:
    """提取页面中指向同域内容的候选链接（去重、去锚点、保序）。"""

    soup = BeautifulSoup(html, "lxml")
    base_domain = urlparse(base_url).netloc
    discovered: list[str] = []
    seen: set[str] = set()

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
        if len(discovered) >= limit:
            break

    return discovered
