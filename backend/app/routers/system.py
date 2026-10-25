import platform
from datetime import datetime
from fastapi import APIRouter, Depends
from app.deps import get_current_user, require_admin
from app.models import User
from app.errors import ok

router = APIRouter(prefix="/system", tags=["system"])

@router.get("/status")
def system_status(user: User = Depends(get_current_user)):
    return ok(data={"status": "healthy", "version": "0.1.0", "timestamp": datetime.utcnow().isoformat(), "platform": platform.machine(), "python": platform.python_version()})

@router.post("/data-purge")
def data_purge(user: User = Depends(require_admin)):
    return ok(message="data purge not yet implemented")

@router.post("/upgrade")
def upgrade(user: User = Depends(require_admin)):
    return ok(data={"status": "not_implemented"})

@router.get("/upgrade/status")
def upgrade_status(user: User = Depends(require_admin)):
    return ok(data={"status": "idle"})


@router.get("/model-policy")
def model_policy(user: User = Depends(require_admin)):
    """当前模型出口模式与边界说明（管理员可见）。"""
    from app.services.model_policy import describe

    return ok(data=describe())
