"""Authentication, session and account-security endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.core.errors import UnauthorizedError
from app.core.ratelimit import limiter
from app.core.security import hash_token
from app.db.session import get_db
from app.dependencies.auth import CurrentPrincipal, get_current_user
from app.models.identity import User
from app.modules.auth import service
from app.modules.auth.schemas import (
    LoginRequest,
    LoginResponse,
    MeResponse,
    OrganizationChoice,
    PasswordChangeResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    PasswordResetResponse,
    RefreshRequest,
    RegisterRequest,
    SessionOut,
)
from app.modules.organizations.schemas import OrganizationOut
from app.modules.users.schemas import ChangePasswordRequest, UserProfile
from app.schemas.common import APIMessage

router = APIRouter(prefix="/auth", tags=["Authentication"])

REFRESH_COOKIE = "resolve_refresh"
COOKIE_PATH = f"{settings.API_V1_PREFIX}/auth"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=token,
        max_age=settings.REFRESH_TOKEN_TTL_DAYS * 86400,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path=COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=REFRESH_COOKIE, path=COOKIE_PATH)


@router.post("/login", response_model=LoginResponse, summary="Sign in and start a session")
@limiter.limit(settings.RATE_LIMIT_LOGIN)
def login(
    request: Request,
    response: Response,
    payload: LoginRequest,
    db: Annotated[Session, Depends(get_db)],
) -> LoginResponse:
    user, organization, membership = service.authenticate(
        db,
        email=payload.email,
        password=payload.password,
        organization_slug=payload.organization_slug,
    )
    result, refresh_raw = service.build_login_response(db, user, organization, membership)
    _set_refresh_cookie(response, refresh_raw)
    return result


@router.post(
    "/register",
    response_model=LoginResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register an organization and its first administrator (development/demo)",
)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
def register(
    request: Request,
    response: Response,
    payload: RegisterRequest,
    db: Annotated[Session, Depends(get_db)],
) -> LoginResponse:
    result, refresh_raw = service.register_organization(db, payload)
    _set_refresh_cookie(response, refresh_raw)
    return result


@router.post("/refresh", response_model=LoginResponse, summary="Rotate the refresh token")
def refresh(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    payload: RefreshRequest | None = None,
) -> LoginResponse:
    raw = (payload.refresh_token if payload else None) or request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise UnauthorizedError("A refresh token is required.", code="missing_refresh_token")
    result, raw_new = service.rotate_refresh_token(db, raw)
    _set_refresh_cookie(response, raw_new)
    return result


@router.post("/logout", response_model=APIMessage, summary="Revoke the current session")
def logout(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    payload: RefreshRequest | None = None,
) -> APIMessage:
    raw = (payload.refresh_token if payload else None) or request.cookies.get(REFRESH_COOKIE)
    if raw:
        service.revoke_token(db, raw, reason="logout")
        db.commit()
    _clear_refresh_cookie(response)
    return APIMessage(message="Signed out.")


@router.get("/me", response_model=MeResponse, summary="Current session context")
def me(principal: CurrentPrincipal, db: Annotated[Session, Depends(get_db)]) -> MeResponse:
    return MeResponse(
        user=UserProfile.model_validate(principal.user),
        organization=OrganizationOut.model_validate(principal.organization),
        role=principal.role,
        permissions=sorted(principal.permissions),
        organizations=service.organization_choices(db, principal.user),
        is_superadmin=principal.is_superadmin,
        demo_mode=settings.DEMO_MODE,
    )


@router.get(
    "/organizations", response_model=list[OrganizationChoice], summary="Organizations for this user"
)
def organizations(
    user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]
) -> list[OrganizationChoice]:
    return service.organization_choices(db, user)


@router.get("/sessions", response_model=list[SessionOut], summary="Active sessions")
def sessions(
    principal: CurrentPrincipal,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> list[SessionOut]:
    current_token = request.cookies.get(REFRESH_COOKIE)
    current_hash = hash_token(current_token) if current_token else None
    rows = service.list_sessions(db, principal.user_id)
    return [
        SessionOut(
            id=row.id,
            user_agent=row.user_agent,
            ip_address=row.ip_address,
            issued_at=row.issued_at,
            expires_at=row.expires_at,
            is_current=row.token_hash == current_hash,
        )
        for row in rows
    ]


@router.delete("/sessions/{session_id}", response_model=APIMessage, summary="Revoke a session")
def revoke_session(
    session_id: uuid.UUID,
    principal: CurrentPrincipal,
    db: Annotated[Session, Depends(get_db)],
) -> APIMessage:
    service.revoke_session(db, principal.user, session_id)
    db.commit()
    return APIMessage(message="Session revoked.")


@router.post("/password-reset", response_model=PasswordResetResponse, summary="Request a password reset")
@limiter.limit(settings.RATE_LIMIT_LOGIN)
def password_reset(
    request: Request,
    payload: PasswordResetRequest,
    db: Annotated[Session, Depends(get_db)],
) -> PasswordResetResponse:
    raw, message = service.request_password_reset(db, payload.email)
    dev_token = raw if (settings.ENV != "production" and settings.DEMO_MODE) else None
    return PasswordResetResponse(message=message, dev_token=dev_token)


@router.post("/password-reset/confirm", response_model=APIMessage, summary="Complete a password reset")
def password_reset_confirm(
    payload: PasswordResetConfirm, db: Annotated[Session, Depends(get_db)]
) -> APIMessage:
    service.confirm_password_reset(db, payload.token, payload.new_password)
    return APIMessage(message="Password updated. Sign in with your new password.")


@router.post("/change-password", response_model=PasswordChangeResponse, summary="Change your password")
def change_password(
    payload: ChangePasswordRequest,
    principal: CurrentPrincipal,
    db: Annotated[Session, Depends(get_db)],
) -> PasswordChangeResponse:
    service.change_password(db, principal.user, payload.current_password, payload.new_password)
    db.commit()
    return PasswordChangeResponse(message="Password changed. Other sessions were signed out.")
