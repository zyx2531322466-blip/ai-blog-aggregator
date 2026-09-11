"""按主机限流，避免对目标站点造成过大压力（T05 / constitution.md 性能要求）。"""

import time
from collections.abc import Callable
from urllib.parse import urlparse


class RateLimiter:
    """保证同一主机的两次请求之间至少间隔 ``min_interval_seconds``。"""

    def __init__(
        self,
        min_interval_seconds: float = 0.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._min_interval = max(0.0, min_interval_seconds)
        self._clock = clock
        self._sleep = sleep
        self._last_request_at: dict[str, float] = {}

    def wait(self, url: str) -> None:
        """在需要时睡眠，使请求满足最小间隔。"""

        if self._min_interval <= 0:
            return
        host = urlparse(url).netloc
        now = self._clock()
        last = self._last_request_at.get(host)
        if last is not None:
            remaining = self._min_interval - (now - last)
            if remaining > 0:
                self._sleep(remaining)
                now = self._clock()
        self._last_request_at[host] = now
