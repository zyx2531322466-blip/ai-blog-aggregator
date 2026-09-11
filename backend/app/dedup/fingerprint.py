"""内容指纹计算（T09 精确去重）。

正文在 T06 解析阶段已剔除站点模板/导航，因此对解析后的正文做
"NFKC 归一化 + 空白折叠"后取 SHA-256，即可判定"正文相同或仅模板差异"。
"""

import hashlib
import re
import unicodedata

_WHITESPACE_RE = re.compile(r"\s+")
_ZERO_WIDTH = ("\u200b", "\ufeff")


def normalize_content(text: str) -> str:
    """归一化正文：统一宽度、去除零宽字符、折叠空白。"""

    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    for char in _ZERO_WIDTH:
        normalized = normalized.replace(char, "")
    normalized = _WHITESPACE_RE.sub(" ", normalized)
    return normalized.strip()


def content_fingerprint(text: str) -> str:
    """返回正文的 SHA-256 指纹（十六进制）。"""

    normalized = normalize_content(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
