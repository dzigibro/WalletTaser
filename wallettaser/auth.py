"""Authentication helpers and API routes."""
from __future__ import annotations

import logging
import os
import secrets
import uuid
from datetime import datetime
from hashlib import pbkdf2_hmac

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, constr
from sqlalchemy import text
from sqlalchemy.orm import Session

from .database import Base, engine, get_session, session_scope
from .models import Tenant, User

security = HTTPBearer()
auth_router = APIRouter(prefix="/auth", tags=["auth"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RegistrationRequest(BaseModel):
    email: EmailStr
    password: constr(min_length=8, max_length=128)


class VerificationRequest(BaseModel):
    email: EmailStr
    code: constr(strip_whitespace=True, min_length=4, max_length=16)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


def _hash_password(password: str, salt: str) -> str:
    return pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000).hex()


def create_user(session: Session, email: str, password: str, tenant: Tenant) -> User:
    salt = secrets.token_hex(16)
    password_hash = _hash_password(password, salt)
    user = User(username=email, password_hash=password_hash, salt=salt, tenant=tenant)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _ensure_user_schema() -> None:
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(users)"))}
        if "is_verified" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 0"))
        if "verification_code" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN verification_code TEXT"))
        if "verified_at" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN verified_at DATETIME"))


def ensure_default_user() -> None:
    _ensure_user_schema()
    with session_scope() as session:
        tenant = session.query(Tenant).filter_by(name="default").first()
        if tenant is None:
            tenant = Tenant(name="default")
            session.add(tenant)
            session.flush()
        user = session.query(User).filter_by(username="demo").first()
        if user is None:
            user = create_user(session, "demo@example.com", "demo", tenant)
        elif user.username == "demo":
            user.username = "demo@example.com"
            session.add(user)
            session.commit()
        if not user.is_verified:
            user.is_verified = True
            user.verification_code = None
            user.verified_at = datetime.utcnow()
            session.add(user)
            session.commit()


def authenticate(session: Session, email: str, password: str) -> User:
    user = session.query(User).filter(User.username == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    expected = _hash_password(password, user.salt)
    if secrets.compare_digest(expected, user.password_hash):
        if not user.is_verified:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="verification_required")
        return user
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")


def issue_token(session: Session, user: User) -> str:
    token = secrets.token_hex(32)
    user.api_token = token
    session.add(user)
    session.commit()
    session.refresh(user)
    return token


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: Session = Depends(get_session),
) -> User:
    token = credentials.credentials
    user = session.query(User).filter(User.api_token == token).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return user


def _generate_verification_code() -> str:
    return f"{secrets.randbelow(900000) + 100000}"


def _send_verification_email(email: str, code: str) -> None:
    logging.info("Verification code for %s: %s", email, code)


def _sanitize_tenant_name(email: str) -> str:
    base = email.split("@", 1)[0].replace(" ", "-") or "tenant"
    return f"tenant-{base}-{uuid.uuid4().hex[:6]}"


def _lookup_user(session: Session, email: str) -> User | None:
    return session.query(User).filter(User.username == email).first()


@auth_router.post("/token", response_model=TokenResponse)
def login(payload: LoginRequest, session: Session = Depends(get_session)) -> TokenResponse:
    user = authenticate(session, payload.email.strip().lower(), payload.password)
    token = issue_token(session, user)
    return TokenResponse(access_token=token)


@auth_router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegistrationRequest, session: Session = Depends(get_session)) -> dict[str, str]:
    email = payload.email.strip().lower()
    if _lookup_user(session, email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email already registered")

    tenant_name = _sanitize_tenant_name(email)
    while session.query(Tenant).filter(Tenant.name == tenant_name).first():
        tenant_name = _sanitize_tenant_name(email)

    tenant = Tenant(name=tenant_name)
    session.add(tenant)
    session.commit()
    session.refresh(tenant)

    user = create_user(session, email, payload.password, tenant)
    code = _generate_verification_code()
    user.is_verified = False
    user.verification_code = code
    user.verified_at = None
    session.add(user)
    session.commit()

    _send_verification_email(email, code)

    response: dict[str, str] = {
        "status": "pending_verification",
        "email": email,
        "message": "Check your email for a verification code.",
    }
    if os.getenv("WALLETTASER_DEV_VERIFICATION_HINT", "1") == "1":
        response["verification_hint"] = code
    return response


@auth_router.post("/verify", response_model=TokenResponse)
def verify_account(payload: VerificationRequest, session: Session = Depends(get_session)) -> TokenResponse:
    email = payload.email.strip().lower()
    user = _lookup_user(session, email)
    if not user or not user.verification_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_verification_state")
    if user.verification_code != payload.code.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_verification_code")

    user.is_verified = True
    user.verification_code = None
    user.verified_at = datetime.utcnow()
    session.add(user)
    session.commit()

    token = issue_token(session, user)
    return TokenResponse(access_token=token)
