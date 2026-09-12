"""外部 LLM 客户端（T25）：知识点提炼、向量化与覆盖判定的可注入抽象。

设计要点：
- 统一走 OpenAI 兼容接口（``/chat/completions`` 与 ``/embeddings``），便于更换供应商或指向自建网关；
- 输出必须是结构化 JSON，做**防御式解析**：非法结构重试，仍失败则抛 ``LlmUnavailable``，
  由上层把文章标记为"待判定"，绝不因为模型异常而中断采集/浏览/推送；
- 通过 ``LlmClient`` 协议注入，测试使用替身实现，**绝不访问真实 API**。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.core.config import Settings


class LlmError(Exception):
    """LLM 调用失败（超时、限流、配额、非法输出等）。"""


@dataclass
class KnowledgePoint:
    """一个知识点：名称 + 摘要 + 若干关键主张。"""

    name: str
    summary: str = ""
    claims: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "summary": self.summary, "claims": list(self.claims)}


@dataclass
class ExtractionResult:
    """一次提炼结果（含用量信息，便于成本统计）。"""

    points: list[KnowledgePoint]
    prompt_tokens: int = 0
    completion_tokens: int = 0
    attempts: int = 1


class LlmClient(Protocol):
    """LLM 能力协议。"""

    def extract_points(self, *, title: str, content: str) -> ExtractionResult:  # pragma: no cover
        """把文章提炼为结构化知识点。"""

    def embed(self, text: str) -> list[float] | None:  # pragma: no cover
        """把文本向量化（返回 None 表示当前环境不支持向量检索）。"""

    def judge_coverage(
        self, *, point: KnowledgePoint, entry_name: str, entry_summary: str
    ) -> bool:  # pragma: no cover
        """二次判定：该知识点是否已被条目完全覆盖（无新增信息）。"""


EXTRACTION_PROMPT = """你是一个知识整理助手。请把给定文章提炼为 1-5 个"知识点"。
要求：
1. 只输出 JSON，不要输出任何解释文字；
2. JSON 结构为 {"points": [{"name": "知识点名称", "summary": "一句话摘要", "claims": ["关键主张"]}]}；
3. 知识点应描述"这篇讲了什么可复用的结论"，而不是文章结构或标题；
4. 若文章没有可提炼的知识点，返回 {"points": []}。
"""

JUDGE_PROMPT = """你在做知识去重判断。已知知识库中已存在的知识点，以及一篇新文章里的知识点。
请判断新知识点是否"已经被完全覆盖"（即没有任何新增信息）。
只输出 JSON：{"covered": true} 或 {"covered": false}。
不确定时一律返回 {"covered": false}。
"""


class OpenAiCompatibleClient:
    """基于 OpenAI 兼容 HTTP 接口的实现（生产使用）。"""

    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self._transport = transport

    @property
    def enabled(self) -> bool:
        return bool(self.settings.llm_api_key)

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            raise LlmError("未配置外部 LLM 密钥（APP_LLM_API_KEY）")
        url = f"{self.settings.llm_base_url.rstrip('/')}/{path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(
                timeout=self.settings.llm_timeout_seconds, transport=self._transport
            ) as client:
                response = client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise LlmError(f"LLM 调用超时：{exc}") from exc
        except httpx.HTTPError as exc:
            raise LlmError(f"LLM 调用失败：{exc}") from exc

        if response.status_code == 429:
            raise LlmError("LLM 限流或配额不足（HTTP 429）")
        if response.status_code >= 400:
            raise LlmError(f"LLM 返回错误状态：HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:  # pragma: no cover - 非 JSON 响应
            raise LlmError("LLM 返回内容不是合法 JSON") from exc

    def _chat_json(
        self, prompt: str, user_content: str, *, attempts: int = 2
    ) -> tuple[dict[str, Any], int, int, int]:
        """调用对话接口并解析 JSON；非法结构会重试 ``attempts`` 次。"""

        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            data = self._post(
                "chat/completions",
                {
                    "model": self.settings.llm_model,
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": user_content},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                },
            )
            usage = data.get("usage") or {}
            try:
                content = data["choices"][0]["message"]["content"]
                return (
                    json.loads(content),
                    int(usage.get("prompt_tokens") or 0),
                    int(usage.get("completion_tokens") or 0),
                    attempt,
                )
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                last_error = exc
        raise LlmError(f"LLM 输出无法解析为约定 JSON：{last_error}")

    def extract_points(self, *, title: str, content: str) -> ExtractionResult:
        payload, prompt_tokens, completion_tokens, attempts = self._chat_json(
            EXTRACTION_PROMPT, f"标题：{title}\n\n正文：\n{content[:8000]}"
        )
        raw_points = payload.get("points")
        if raw_points is None or not isinstance(raw_points, list):
            raise LlmError("LLM 输出缺少 points 字段")
        points: list[KnowledgePoint] = []
        for item in raw_points:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            claims = item.get("claims")
            points.append(
                KnowledgePoint(
                    name=str(item["name"]).strip()[:300],
                    summary=str(item.get("summary") or "").strip(),
                    claims=[str(claim) for claim in claims] if isinstance(claims, list) else [],
                )
            )
        return ExtractionResult(
            points=points,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            attempts=attempts,
        )

    def embed(self, text: str) -> list[float] | None:
        if not self.enabled:
            return None
        data = self._post("embeddings", {"model": self.settings.llm_model, "input": text[:4000]})
        try:
            vector = data["data"][0]["embedding"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmError(f"embedding 响应结构异常：{exc}") from exc
        return [float(value) for value in vector]

    def judge_coverage(self, *, point: KnowledgePoint, entry_name: str, entry_summary: str) -> bool:
        payload, _, _, _ = self._chat_json(
            JUDGE_PROMPT,
            (
                f"知识库已有知识点：{entry_name}\n{entry_summary}\n\n"
                f"新文章的知识点：{point.name}\n{point.summary}\n"
                f"关键主张：{'；'.join(point.claims)}"
            ),
        )
        return bool(payload.get("covered") is True)


class StaticLlmClient:
    """替身实现：按预置脚本返回结果，用于测试与本地演示（不触网）。"""

    def __init__(
        self,
        *,
        points: list[KnowledgePoint] | None = None,
        fail_times: int = 0,
        cover_when: str | None = None,
        embedding: list[float] | None = None,
        embeddings: dict[str, list[float]] | None = None,
    ) -> None:
        self.points = points if points is not None else []
        self.fail_times = fail_times
        self.cover_when = cover_when
        self.embedding = embedding
        # 按"文本包含的关键字"返回不同向量：用于让不同知识点落在不同的语义方向
        self.embeddings = embeddings or {}
        self.extract_calls: list[str] = []
        self.embed_calls: list[str] = []
        self.judge_calls: list[tuple[str, str]] = []
        self.attempts = 0

    def extract_points(self, *, title: str, content: str) -> ExtractionResult:
        self.attempts += 1
        self.extract_calls.append(title)
        if self.attempts <= self.fail_times:
            raise LlmError("模拟 LLM 不可用")
        return ExtractionResult(points=list(self.points), attempts=1)

    def embed(self, text: str) -> list[float] | None:
        self.embed_calls.append(text)
        for keyword, vector in self.embeddings.items():
            if keyword in text:
                return list(vector)
        if self.embedding is not None:
            return list(self.embedding)
        # 未提供向量时给出一个稳定的伪向量，保证相似度计算可用且可预期
        return [float(len(text) % 7), 1.0, 0.0]

    def judge_coverage(self, *, point: KnowledgePoint, entry_name: str, entry_summary: str) -> bool:
        self.judge_calls.append((point.name, entry_name))
        if self.cover_when is None:
            return False
        return self.cover_when in point.name or self.cover_when in entry_name


def build_llm_client(settings: Settings) -> LlmClient:
    """按配置构造 LLM 客户端。"""

    return OpenAiCompatibleClient(settings)
