"""统一错误响应。

错误响应格式与 `plan.md` 保持一致::

    {"error": {"code": "NOT_FOUND", "message": "文章不存在"}}
"""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    """业务层可直接抛出的带错误码异常。"""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def error_payload(code: str, message: str, details: Any | None = None) -> dict[str, Any]:
    """构造统一错误响应体。"""

    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    return payload


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器，保证所有错误响应格式统一。"""

    @app.exception_handler(ApiError)
    async def _handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else "请求处理失败"
        return JSONResponse(status_code=exc.status_code, content=error_payload(code, message))

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_payload(
                "VALIDATION_ERROR", "请求参数校验失败", jsonable_encoder(exc.errors())
            ),
        )


_HTTP_STATUS_CODES = {
    status.HTTP_400_BAD_REQUEST: "BAD_REQUEST",
    status.HTTP_401_UNAUTHORIZED: "UNAUTHORIZED",
    status.HTTP_403_FORBIDDEN: "FORBIDDEN",
    status.HTTP_404_NOT_FOUND: "NOT_FOUND",
    status.HTTP_409_CONFLICT: "CONFLICT",
    422: "VALIDATION_ERROR",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "INTERNAL_ERROR",
}
