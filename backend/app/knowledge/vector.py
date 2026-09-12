"""向量相似度与检索（T25）。

实现说明（与 `plan.md` 的差异已在收敛报告中登记）：
- 计划中提出使用 pgvector；本次实现采用**可移植方案**：向量以 JSON 数组存储，
  相似度在应用层计算余弦距离。这样 SQLite（本地/测试）与 PostgreSQL（生产）行为一致，
  且不引入数据库扩展依赖；
- 通过 ``VectorIndex`` 抽象保留替换点：规模增长后可在不改调用方的前提下换成 pgvector 索引。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """余弦相似度；维度不一致或零向量时返回 0（不抛异常，便于稳健降级）。"""

    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def keyword_similarity(left: str, right: str) -> float:
    """降级用的字符级相似度（Jaccard on 2-gram），用于没有向量的环境。"""

    def bigrams(text: str) -> set[str]:
        cleaned = "".join(ch for ch in text.lower() if ch.strip())
        return {cleaned[i : i + 2] for i in range(max(len(cleaned) - 1, 0))} or {cleaned}

    left_set, right_set = bigrams(left), bigrams(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


@dataclass
class VectorCandidate:
    """一条候选（条目 id + 相似度）。"""

    entry_id: str
    similarity: float


class VectorIndex:
    """向量检索抽象：调用方只依赖 ``search`` / ``search_text``。"""

    def __init__(self, *, min_similarity: float = 0.0) -> None:
        self.min_similarity = min_similarity

    def search(
        self,
        query: Sequence[float] | None,
        entries: Iterable[tuple[str, Sequence[float] | None, str]],
        *,
        query_text: str | None = None,
    ) -> list[VectorCandidate]:
        """按相似度召回候选，降序返回。

        ``entries`` 为 ``(entry_id, embedding, text)``：
        - 双方都有向量时用余弦相似度；
        - 任一侧缺少向量（例如人工录入的条目没有向量）时退化为字符级相似度，
          保证不因缺向量而完全失效。
        """

        results: list[VectorCandidate] = []
        for entry_id, embedding, text in entries:
            if query and embedding:
                similarity = cosine_similarity(query, embedding)
            elif query_text:
                similarity = keyword_similarity(query_text, text)
            else:
                similarity = 0.0
            results.append(VectorCandidate(entry_id=entry_id, similarity=similarity))
        results.sort(key=lambda item: item.similarity, reverse=True)
        return [item for item in results if item.similarity >= self.min_similarity]

    def search_text(self, query: str, entries: Iterable[tuple[str, str]]) -> list[VectorCandidate]:
        """无向量时的降级检索（字符级相似度）。"""

        results = [
            VectorCandidate(entry_id=entry_id, similarity=keyword_similarity(query, text))
            for entry_id, text in entries
        ]
        results.sort(key=lambda item: item.similarity, reverse=True)
        return [item for item in results if item.similarity >= self.min_similarity]
