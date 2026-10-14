from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession as SAAsyncSession

from app.core.deps import get_db, require_role
from app.models.alert import Alert
from app.models.user import User
from app.schemas.alert import AlertCreate, AlertOut, AlertUpdate

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=List[AlertOut])
async def list_alerts(
    db: SAAsyncSession = Depends(get_db),
    _user: User = Depends(require_role("admin", "operator")),
):
    result = await db.execute(select(Alert).order_by(Alert.id.desc()))
    return result.scalars().all()


@router.get("/{alert_id}", response_model=AlertOut)
async def get_alert(
    alert_id: int,
    db: SAAsyncSession = Depends(get_db),
    _user: User = Depends(require_role("admin", "operator")),
):
    alert = await db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="alert not found")
    return alert


@router.post("", response_model=AlertOut, status_code=status.HTTP_201_CREATED)
async def create_alert(
    body: AlertCreate,
    db: SAAsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "operator")),
):
    alert = Alert(
        plate_number=body.plate_number,
        reason=body.reason,
        created_by=user.id,
        is_active=True,
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return alert


@router.put("/{alert_id}", response_model=AlertOut)
async def update_alert(
    alert_id: int,
    body: AlertUpdate,
    db: SAAsyncSession = Depends(get_db),
    _user: User = Depends(require_role("admin", "operator")),
):
    alert = await db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="alert not found")
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(alert, field, value)
    await db.commit()
    await db.refresh(alert)
    return alert


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(
    alert_id: int,
    db: SAAsyncSession = Depends(get_db),
    _user: User = Depends(require_role("admin", "operator")),
):
    alert = await db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="alert not found")
    try:
        await db.delete(alert)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete alert with associated triggers",
        )
