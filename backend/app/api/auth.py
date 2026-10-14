import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as SAAsyncSession

from app.core.deps import get_current_user, get_db
from app.core.rate_limiter import check_auth_rate_limit
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import LoginRequest, RefreshRequest, TokenResponse, UserOut
from app.services.audit import write_audit_log

router = APIRouter(prefix="/auth", tags=["auth"])

DUMMY_HASH = "$2b$12$e86gkz.a2X757UvjLrq/juIviqF7wYyO0W41/0088Z6FmU71yVbfe"


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(check_auth_rate_limit)])
async def login(
    request: Request,
    body: Optional[LoginRequest] = None,
    db: SAAsyncSession = Depends(get_db),
):
    email = None
    password = None

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            data = await request.json()
            email = data.get("email") or data.get("username")
            password = data.get("password")
        except Exception:
            pass
    elif "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        email = form.get("username") or form.get("email")
        password = form.get("password")
    elif body is not None:
        email = body.email
        password = body.password
    else:
        try:
            data = await request.json()
            email = data.get("email") or data.get("username")
            password = data.get("password")
        except Exception:
            pass

    if not email or not password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="email and password are required",
        )

    user = await db.scalar(select(User).where(User.email == str(email)))
    if user:
        password_matches = await asyncio.to_thread(
            verify_password, str(password), user.password_hash
        )
    else:
        await asyncio.to_thread(verify_password, str(password), DUMMY_HASH)
        password_matches = False

    if not user or not password_matches:
        await write_audit_log(
            db,
            user_id=user.id if user else None,
            action="login_failed",
            resource="auth",
            resource_id=str(email),
            ip=request.client.host if request.client else None,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="bad credentials"
        )

    if not user.is_active:
        await write_audit_log(
            db,
            user_id=user.id,
            action="login_failed",
            resource="auth",
            resource_id=str(email),
            ip=request.client.host if request.client else None,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="account disabled"
        )

    role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
    access = create_access_token(user.id, role_val)
    refresh = create_refresh_token(user.id)
    await write_audit_log(
        db,
        user_id=user.id,
        action="login",
        resource="auth",
        ip=request.client.host if request.client else None,
    )
    await db.commit()
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenResponse, dependencies=[Depends(check_auth_rate_limit)])
async def refresh(
    body: RefreshRequest,
    request: Request,
    db: SAAsyncSession = Depends(get_db),
):
    payload = decode_token(body.refresh_token)
    if not payload or payload.get("type") != "refresh":
        await write_audit_log(
            db,
            user_id=None,
            action="refresh_failed",
            resource="auth",
            ip=request.client.host if request.client else None,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid refresh token"
        )

    sub = payload.get("sub")
    if not sub:
        await write_audit_log(
            db,
            user_id=None,
            action="refresh_failed",
            resource="auth",
            ip=request.client.host if request.client else None,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing sub claim"
        )

    try:
        user_id = int(sub)
    except (ValueError, TypeError):
        await write_audit_log(
            db,
            user_id=None,
            action="refresh_failed",
            resource="auth",
            ip=request.client.host if request.client else None,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid sub claim"
        )

    user = await db.scalar(select(User).where(User.id == user_id))
    if not user or not user.is_active:
        await write_audit_log(
            db,
            user_id=user_id if user else None,
            action="refresh_failed",
            resource="auth",
            ip=request.client.host if request.client else None,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found"
        )

    role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
    access = create_access_token(user.id, role_val)
    refresh_tok = create_refresh_token(user.id)
    return TokenResponse(access_token=access, refresh_token=refresh_tok)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user
