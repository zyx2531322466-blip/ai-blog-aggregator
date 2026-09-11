"""测试用假对象（避免依赖真实网络）。"""

from pathlib import Path

from app.crawler.fetcher import FetchResult

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name: str) -> str:
    """读取 tests/fixtures 下的 HTML fixture。"""

    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


class StaticFetcher:
    """按 URL 返回预置内容的抓取器，记录调用过的 URL。"""

    def __init__(
        self,
        pages: dict[str, str] | None = None,
        *,
        failures: dict[str, str] | None = None,
        status_overrides: dict[str, int] | None = None,
    ) -> None:
        self.pages = pages or {}
        self.failures = failures or {}
        self.status_overrides = status_overrides or {}
        self.calls: list[str] = []

    def fetch(self, url: str) -> FetchResult:
        self.calls.append(url)
        if url in self.failures:
            return FetchResult(url=url, status_code=None, text=None, error=self.failures[url])
        status = self.status_overrides.get(url, 200)
        if url not in self.pages:
            return FetchResult(url=url, status_code=404, text=None, error=None)
        if not 200 <= status < 300:
            return FetchResult(url=url, status_code=status, text=None, error=None)
        return FetchResult(url=url, status_code=status, text=self.pages[url])


class RaisingFetcher:
    """对指定 URL 抛异常的抓取器，用于验证失败捕获。"""

    def __init__(
        self, pages: dict[str, str] | None = None, *, raise_for: set[str] | None = None
    ) -> None:
        self._static = StaticFetcher(pages)
        self.raise_for = raise_for or set()
        self.calls: list[str] = []

    def fetch(self, url: str) -> FetchResult:
        self.calls.append(url)
        if url in self.raise_for:
            raise ConnectionError(f"无法连接: {url}")
        return self._static.fetch(url)
