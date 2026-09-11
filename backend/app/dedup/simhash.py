"""SimHash 近似指纹（T13）。

用于识别转载、镜像、微小改写等"非完全一致但高度相似"的内容：
- 对正文分词（英文按单词、中文按字符二元组）后计算 64 位 SimHash；
- 以汉明距离衡量相似度：``similarity = 1 - distance / 64``。

注意：SimHash 值按"有符号 64 位"落库（兼容 PostgreSQL BIGINT），
读写时通过 :func:`to_signed64` / :func:`from_signed64` 转换。
"""

import hashlib
import re

from app.dedup.fingerprint import normalize_content

BITS = 64
_SIGN_BIT = 1 << (BITS - 1)
_MASK = (1 << BITS) - 1
_WORD_RE = re.compile(r"[A-Za-z0-9_]+")


def _tokenize(text: str) -> list[str]:
    normalized = normalize_content(text)
    words = _WORD_RE.findall(normalized.lower())
    cjk_chars = [char for char in normalized if "\u4e00" <= char <= "\u9fff"]
    bigrams = [cjk_chars[i] + cjk_chars[i + 1] for i in range(len(cjk_chars) - 1)]
    return words + bigrams


def compute_simhash(text: str, bits: int = BITS) -> int:
    """计算文本的 SimHash（返回无符号整数）。"""

    tokens = _tokenize(text)
    if not tokens:
        return 0

    vector = [0] * bits
    for token in tokens:
        digest = hashlib.md5(token.encode("utf-8")).digest()
        token_hash = int.from_bytes(digest[:8], "big")
        for index in range(bits):
            vector[index] += 1 if token_hash & (1 << index) else -1

    result = 0
    for index in range(bits):
        if vector[index] > 0:
            result |= 1 << index
    return result


def hamming_distance(left: int, right: int, bits: int = BITS) -> int:
    """两个指纹的汉明距离。"""

    mask = (1 << bits) - 1
    return bin((left ^ right) & mask).count("1")


def simhash_similarity(left: int, right: int, bits: int = BITS) -> float:
    """相似度（0.0 - 1.0）。"""

    return 1.0 - hamming_distance(left, right, bits) / bits


def to_signed64(value: int) -> int:
    """转换为有符号 64 位整数（用于 PostgreSQL BIGINT 存储）。"""

    value &= _MASK
    return value - (1 << BITS) if value & _SIGN_BIT else value


def from_signed64(value: int) -> int:
    """由有符号 64 位还原为无符号指纹。"""

    return value & _MASK
