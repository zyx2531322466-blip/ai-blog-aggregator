"""应用配置。

配置项通过环境变量注入，便于本地开发（默认 SQLite）与
Docker/生产环境（PostgreSQL）使用同一套代码。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用级配置。所有字段均可通过同名（大写）环境变量覆盖。"""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_", extra="ignore")

    app_name: str = "Blog Aggregator"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"

    # 数据库：本地/测试默认 SQLite；生产通过 APP_DATABASE_URL 注入 PostgreSQL。
    database_url: str = "sqlite:///./data/app.db"

    # 缓存/任务队列（T17 调度器可选使用）。
    redis_url: str = "redis://localhost:6379/0"

    # 维护者受控入口使用的管理令牌（T03 消费）；生产必须通过环境变量覆盖。
    admin_token: str = "change-me-in-production"
    # 维护者审计名称（T15 变更记录中的"谁"），非用户账户。
    admin_actor: str = "admin"

    # 允许的前端来源，用于 CORS。
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # 爬虫礼貌性配置（T05）：User-Agent、超时、单站点最小请求间隔与单次最大页数。
    crawler_user_agent: str = "BlogAggregatorBot/0.1 (+https://example.com/bot)"
    crawler_timeout_seconds: float = 10.0
    crawler_min_interval_seconds: float = 1.0
    crawler_max_pages_per_run: int = 20


@lru_cache
def get_settings() -> Settings:
    """返回进程内缓存的配置单例。"""

    return Settings()
