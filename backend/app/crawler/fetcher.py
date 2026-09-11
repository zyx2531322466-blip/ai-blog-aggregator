"""HTTP 抓取器。

通过 ``Fetcher`` 协议抽象网络访问，便于：
- 单元测试注入假抓取器（fixtures，不依赖真实网络，见 constitution.md 测试规范）；
- 生产环境使用 ``HttpxFetcher``（支持注入 transport，便于录制回放）。
"""

from dataclasses import dataclass
from typing import Protocol

import httpx

DEFAULT_USER_AGENT = "BlogAggregatorBot/0.1 (+https://example.com/bot)"


@dataclass(frozen=True)
class FetchResult:
    """单次抓取结果（成功或失败，不抛异常）。"""

    url: str
    status_code: int | None
    text: str | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.status_code is not None and 200 <= self.status_code < 300


class Fetcher(Protocol):
    """抓取器协议。"""

    def fetch(self, url: str) -> FetchResult:  # pragma: no cover - 协议定义
        ...


class HttpxFetcher:
    """基于 httpx 的同步抓取器。"""

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=timeout_seconds,
            follow_redirects=True,
            transport=transport,
        )

    def fetch(self, url: str) -> FetchResult:
        """抓取单个 URL；任何网络异常都被捕获并转成失败结果。"""

        try:
            response = self._client.get(url)
        except httpx.HTTPError as exc:
            return FetchResult(url=url, status_code=None, text=None, error=str(exc))
        return FetchResult(url=url, status_code=response.status_code, text=response.text)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HttpxFetcher":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
