"""robots.txt 遵守策略（T05 / constitution.md 的爬取礼貌性要求）。"""

from typing import Protocol
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from app.crawler.fetcher import Fetcher


class RobotsChecker(Protocol):
    """robots 判定协议。"""

    def can_fetch(self, url: str) -> bool:  # pragma: no cover - 协议定义
        ...


class AllowAllRobots:
    """允许全部（默认；也用于测试注入）。"""

    def can_fetch(self, url: str) -> bool:
        return True


class DenyAllRobots:
    """拒绝全部（用于测试 robots 分支）。"""

    def can_fetch(self, url: str) -> bool:
        return False


class RobotFilePolicy:
    """按目标站 ``/robots.txt`` 判定是否允许抓取。"""

    def __init__(self, fetcher: Fetcher, user_agent: str = "*") -> None:
        self._fetcher = fetcher
        self._user_agent = user_agent
        self._parsers: dict[str, RobotFileParser] = {}

    def can_fetch(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        parser = self._parsers.get(origin)
        if parser is None:
            parser = self._load(origin)
            self._parsers[origin] = parser
        return parser.can_fetch(self._user_agent, url)

    def _load(self, origin: str) -> RobotFileParser:
        parser = RobotFileParser()
        result = self._fetcher.fetch(f"{origin}/robots.txt")
        if result.ok and result.text is not None:
            parser.parse(result.text.splitlines())
        else:
            # 无法获取 robots.txt（404/网络错误）时按允许处理，保持宽松但可配置
            parser.parse([])
        return parser
