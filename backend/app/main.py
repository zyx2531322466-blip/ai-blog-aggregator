"""FastAPI 应用工厂。

T01 阶段只提供可运行的空应用与基础设施健康探针；
T03 起挂载 `api/v1` 路由与统一错误处理；
T07 起在启动时初始化默认类别（测试环境跳过，避免污染测试数据库）。
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1 import api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers


def _bootstrap_defaults() -> None:
    """在非测试环境初始化数据库表与默认类别。"""

    from app.db.session import get_session_factory, init_db
    from app.services.category_service import ensure_default_categories

    init_db()
    session = get_session_factory()()
    try:
        ensure_default_categories(session)
    finally:
        session.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    """创建并配置 FastAPI 应用实例。"""

    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if settings.environment != "test":
            _bootstrap_defaults()
        yield

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/healthz", tags=["infra"])
    def healthz() -> dict[str, str]:
        """基础设施健康探针，供容器编排与 CI 使用（非业务接口）。"""

        return {"status": "ok", "version": __version__}

    return app


app = create_app()
