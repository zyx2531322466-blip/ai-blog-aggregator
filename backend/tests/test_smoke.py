"""T01 占位测试：验证测试框架可运行，以及空应用可正常创建。

本文件刻意不包含任何业务断言，仅用于打通 CI 中的测试流水线。
"""

from app import __version__
from app.main import create_app


def test_test_framework_is_wired() -> None:
    """占位断言：确保 pytest 能在本项目中发现并执行测试。"""

    assert True


def test_empty_app_can_be_created() -> None:
    """项目应能创建 FastAPI 应用，并暴露基础设施健康探针。"""

    app = create_app()
    routes = {getattr(route, "path", None) for route in app.routes}
    assert "/healthz" in routes
    assert app.title
    assert __version__
