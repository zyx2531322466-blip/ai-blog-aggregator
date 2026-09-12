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

    # ------------------------------------------------------------------
    # v2 订阅与邮件推送（T22–T24）
    # ------------------------------------------------------------------
    # 对外可达的站点地址：用于生成确认/退订链接（必须是订阅者能打开的地址）。
    public_base_url: str = "http://localhost:3000"
    # 真实发信开关：默认关闭，避免误发；测试与本地预演只记录不投递。
    mail_enabled: bool = False
    smtp_host: str = "localhost"
    smtp_port: int = 1025  # 默认指向本地邮件捕获工具（Mailpit/MailHog）
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = False
    mail_from: str = "no-reply@example.com"
    # 确认凭证有效期（小时）与反滥用频控（每邮箱/IP 每小时最多创建次数）。
    subscription_confirm_ttl_hours: int = 24
    subscription_rate_limit_per_hour: int = 3
    # 推送默认设置（可由维护者通过 notification_settings 覆盖）。
    digest_default_frequency: str = "weekly"
    digest_max_items: int = 10
    digest_send_window_start_hour: int = 9
    digest_send_window_end_hour: int = 21
    digest_send_empty: bool = False
    digest_max_retries: int = 3
    # 退信率超过该比例时自动暂停推送（T24 送达合规）。
    bounce_pause_threshold: float = 0.05

    # ------------------------------------------------------------------
    # v2 知识级去重（T25–T26）
    # ------------------------------------------------------------------
    # 外部 LLM（OpenAI 兼容接口）；默认关闭知识去重，先观察再开启。
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 30.0
    llm_max_calls_per_run: int = 200
    knowledge_enabled: bool = False
    # 保守阈值：达到高阈值才判"已覆盖"；中间区间交模型二次判定。
    knowledge_similarity_high: float = 0.92
    knowledge_similarity_low: float = 0.80
    knowledge_prompt_version: str = "knowledge-v1"

    # 爬虫礼貌性配置（T05）：User-Agent、超时、单站点最小请求间隔与单次最大页数。
    crawler_user_agent: str = "BlogAggregatorBot/0.1 (+https://example.com/bot)"
    crawler_timeout_seconds: float = 10.0
    crawler_min_interval_seconds: float = 1.0
    crawler_max_pages_per_run: int = 20


@lru_cache
def get_settings() -> Settings:
    """返回进程内缓存的配置单例。"""

    return Settings()
