"""维护者访问控制基础设施（T03）。

说明：本模块提供的是"维护者受控入口"的访问控制，**不是**普通用户账户体系
（spec 的非目标）。所有维护者专属接口通过 ``require_admin`` 依赖复用本机制；
普通浏览类接口不挂载该依赖，保持匿名可访问。

具体校验方式采用管理令牌（Bearer Token），实现细节属于 plan.md 范畴，
后续如需替换为 JWT/内网限制，只需替换本模块而不影响各业务接口。
"""

import secrets
from dataclasses import dataclass

from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.core.errors import ApiError

_bearer_scheme = HTTPBearer(auto_error=False, description="维护者管理令牌 (Bearer)")


@dataclass(frozen=True)
class AdminPrincipal:
    """通过校验的维护者身份（仅含用于审计的名称，不涉及用户账户）。"""

    actor: str


def authenticate_admin_token(token: str | None, settings: Settings) -> AdminPrincipal | None:
    """校验令牌，成功返回维护者身份，失败返回 ``None``。

    使用常量时间比较，避免令牌比较被时序侧信道利用。
    """

    if not token or not settings.admin_token:
        return None
    if secrets.compare_digest(token, settings.admin_token):
        return AdminPrincipal(actor=settings.admin_actor)
    return None


def get_admin_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> AdminPrincipal:
    """FastAPI 依赖：要求请求携带有效的维护者令牌。"""

    token = credentials.credentials if credentials is not None else None
    principal = authenticate_admin_token(token, settings)
    if principal is None:
        raise ApiError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="UNAUTHORIZED",
            message="维护者身份校验失败，请提供有效的管理令牌",
        )
    return principal


# 语义化别名：所有维护者接口统一使用该依赖。
require_admin = get_admin_principal
