"""Authentication helpers and API routes."""
from __future__ import annotations

import secrets
from hashlib import pbkdf2_hmac
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, constr
from sqlalchemy.orm import Session

from .database import Base, engine, get_session, session_scope
from .models import Tenant, User

security = HTTPBearer()
auth_router = APIRouter(prefix="/auth", tags=["auth"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RegistrationRequest(BaseModel):
    username: constr(strip_whitespace=True, min_length=3, max_length=64)
    password: constr(min_length=8, max_length=128)
    tenant_name: constr(strip_whitespace=True, min_length=1, max_length=128) | None = None


def _hash_password(password: str, salt: str) -> str:
    return pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000).hex()


def create_user(session: Session, username: str, password: str, tenant: Tenant) -> User:
    salt = secrets.token_hex(16)
    password_hash = _hash_password(password, salt)
    user = User(username=username, password_hash=password_hash, salt=salt, tenant=tenant)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def ensure_default_user() -> None:
    Base.metadata.create_all(bind=engine)
    with session_scope() as session:
        tenant = session.query(Tenant).filter_by(name="default").first()
        if tenant is None:
            tenant = Tenant(name="default")
            session.add(tenant)
            session.flush()
        user = session.query(User).filter_by(username="demo").first()
        if user is None:
            create_user(session, "demo", "demo", tenant)


def authenticate(session: Session, username: str, password: str) -> User:
    user = session.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    expected = _hash_password(password, user.salt)
    if secrets.compare_digest(expected, user.password_hash):
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


class LoginRequest(BaseModel):
    username: str
    password: str


@auth_router.post("/token", response_model=TokenResponse)
def login(payload: LoginRequest, session: Session = Depends(get_session)) -> TokenResponse:
    user = authenticate(session, payload.username, payload.password)
    token = issue_token(session, user)
    return TokenResponse(access_token=token)


@auth_router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegistrationRequest, session: Session = Depends(get_session)) -> TokenResponse:
    username = payload.username.strip()
    existing_user = session.query(User).filter(User.username == username).first()
    if existing_user:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="username already registered")

    desired_tenant = (payload.tenant_name or username).strip()
    tenant_name = desired_tenant or f"tenant-{uuid.uuid4().hex[:8]}"

    if session.query(Tenant).filter(Tenant.name == tenant_name).first():
        tenant_name = f"{tenant_name}-{uuid.uuid4().hex[:6]}"

    tenant = Tenant(name=tenant_name)
    session.add(tenant)
    session.commit()
    session.refresh(tenant)

    user = create_user(session, username, payload.password, tenant)
    token = issue_token(session, user)
    return TokenResponse(access_token=token)
