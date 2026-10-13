from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession as SAAsyncSession

from app.models.audit_log import AuditLog


async def write_audit_log(
    db: SAAsyncSession,
    user_id: Optional[int],
    action: str,
    resource: str,
    resource_id: Optional[str] = None,
    ip: Optional[str] = None,
) -> None:
    log = AuditLog(
        user_id=user_id,
        action=action,
        resource=resource,
        resource_id=resource_id,
        ip=ip,
    )
    db.add(log)
    await db.flush()
