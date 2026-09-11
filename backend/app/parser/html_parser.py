"""HTML 结构化解析（T06）。

策略（无需外部正文抽取库，基于 lxml/BeautifulSoup 的启发式）：
1. 标题：og:title / twitter:title → 首个 h1 → <title>；
2. 正文：<article> → 常见正文容器（.post-content 等）→ <main> → 全文正文；
3. 发布时间：article:published_time 等 meta → <time datetime> → JSON-LD datePublished；
4. 作者：meta name=author → article:author → JSON-LD author.name。

解析失败（缺少标题或正文过短）抛出 ``ParseError``，由上层标记为异常状态。
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup, Tag
from dateutil import parser as date_parser

_STRIP_TAGS = ("script", "style", "nav", "header", "footer", "aside", "form", "noscript")
_CONTENT_SELECTORS = (
    "article",
    "[itemprop='articleBody']",
    "div.post-content",
    "div.entry-content",
    "div.article-content",
    "main",
)
_MIN_CONTENT_LENGTH = 10


class ParseError(Exception):
    """无法从 HTML 中提取有效内容。"""


@dataclass(frozen=True)
class ParsedArticle:
    """解析结果。"""

    title: str
    content: str
    published_at: datetime | None = None
    author: str | None = None


def parse_html(html: str, url: str) -> ParsedArticle:
    """从 HTML 解析文章；失败时抛出 :class:`ParseError`。"""

    if not html or not html.strip():
        raise ParseError("原始 HTML 为空")

    soup = BeautifulSoup(html, "lxml")
    jsonld = _extract_jsonld(soup)

    title = _extract_title(soup) or _jsonld_str(jsonld, "headline")
    if not title:
        raise ParseError("未能提取标题")

    content = _extract_content(soup)
    if len(content) < _MIN_CONTENT_LENGTH:
        raise ParseError("未能提取有效正文")

    return ParsedArticle(
        title=title.strip(),
        content=content,
        published_at=_extract_published_at(soup, jsonld),
        author=_extract_author(soup, jsonld),
    )


def _meta_content(soup: BeautifulSoup, **attrs: str) -> str | None:
    tag = soup.find("meta", attrs=attrs)
    if tag is not None and tag.get("content"):
        return str(tag["content"]).strip()
    return None


def _extract_title(soup: BeautifulSoup) -> str | None:
    for attrs in (
        {"property": "og:title"},
        {"name": "og:title"},
        {"name": "twitter:title"},
    ):
        value = _meta_content(soup, **attrs)
        if value:
            return value

    heading = soup.find("h1")
    if heading is not None and heading.get_text(strip=True):
        return heading.get_text(strip=True)

    if soup.title is not None and soup.title.get_text(strip=True):
        return soup.title.get_text(strip=True)
    return None


def _extract_content(soup: BeautifulSoup) -> str:
    for tag in soup(_STRIP_TAGS):
        tag.decompose()

    container: Tag | None = None
    for selector in _CONTENT_SELECTORS:
        container = soup.select_one(selector)
        if container is not None:
            break
    if container is None:
        container = soup.body or soup

    blocks = [
        text
        for text in (
            tag.get_text(" ", strip=True)
            for tag in container.find_all(["p", "h2", "h3", "li", "blockquote", "pre"])
        )
        if text
    ]
    if not blocks:
        blocks = [container.get_text(" ", strip=True)]

    content = "\n\n".join(blocks)
    return _normalize_whitespace(content)


def _extract_published_at(soup: BeautifulSoup, jsonld: Any) -> datetime | None:
    for attrs in (
        {"property": "article:published_time"},
        {"property": "og:published_time"},
        {"name": "article:published_time"},
        {"itemprop": "datePublished"},
        {"name": "pubdate"},
        {"name": "date"},
    ):
        value = _meta_content(soup, **attrs)
        parsed = _try_parse_datetime(value)
        if parsed is not None:
            return parsed

    time_tag = soup.find("time")
    if isinstance(time_tag, Tag):
        parsed = _try_parse_datetime(time_tag.get("datetime") or time_tag.get_text(strip=True))
        if parsed is not None:
            return parsed

    return _try_parse_datetime(_jsonld_str(jsonld, "datePublished"))


def _extract_author(soup: BeautifulSoup, jsonld: Any) -> str | None:
    for attrs in (
        {"name": "author"},
        {"property": "article:author"},
        {"name": "article:author"},
    ):
        value = _meta_content(soup, **attrs)
        if value:
            return value

    author = jsonld.get("author") if isinstance(jsonld, dict) else None
    if isinstance(author, dict) and author.get("name"):
        return str(author["name"]).strip()
    if isinstance(author, str) and author.strip():
        return author.strip()
    return None


def _extract_jsonld(soup: BeautifulSoup) -> dict[str, Any]:
    """提取并合并 JSON-LD 结构，失败时返回空字典。"""

    result: dict[str, Any] = {}
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        for item in _iter_jsonld_items(data):
            for key, value in item.items():
                result.setdefault(key, value)
    return result


def _iter_jsonld_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        if "@graph" in data and isinstance(data["@graph"], list):
            return [item for item in data["@graph"] if isinstance(item, dict)]
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _jsonld_str(jsonld: Any, key: str) -> str | None:
    if isinstance(jsonld, dict):
        value = jsonld.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _try_parse_datetime(value: object) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return date_parser.parse(value)
    except (ValueError, OverflowError):
        return None


def _normalize_whitespace(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    return "\n\n".join(line for line in lines if line)
