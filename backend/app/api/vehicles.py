from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession as SAAsyncSession

from app.core.deps import get_db, require_role
from app.models.user import User
from app.services.audit import write_audit_log

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


@router.get("/{plate}/trajectory")
async def get_trajectory(
    plate: str,
    request: Request,
    db: SAAsyncSession = Depends(get_db),
    user: User = Depends(require_role("operator", "admin")),
):
    await write_audit_log(
        db,
        user_id=user.id,
        action="trace",
        resource="vehicles",
        resource_id=plate,
        ip=request.client.host if request.client else None,
    )
    await db.commit()
    # stub: will be implemented in Step 10
    return {"plate": plate, "trajectory": [], "message": "stub: not yet implemented"}
