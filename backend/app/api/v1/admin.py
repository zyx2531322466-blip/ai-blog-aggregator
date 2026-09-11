"""维护者专属接口（均需通过 T03 的访问控制）。"""

from fastapi import APIRouter, Depends

from app.core.security import AdminPrincipal, require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/ping")
def admin_ping(principal: AdminPrincipal = Depends(require_admin)) -> dict[str, str]:
    """受控探针：验证访问控制基础设施是否生效，并回显审计身份。"""

    return {"status": "ok", "actor": principal.actor}
