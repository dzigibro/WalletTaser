"""SQLAlchemy ORM models."""
from __future__ import annotations

from datetime import datetime
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, Boolean
from sqlalchemy.orm import relationship

from .database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    salt = Column(String, nullable=False)
    api_token = Column(String, unique=True, nullable=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    is_verified = Column(Boolean, nullable=False, default=False)
    verification_code = Column(String, nullable=True)
    verified_at = Column(DateTime, nullable=True)

    tenant = relationship("Tenant", backref="users")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    filename = Column(String, nullable=False)
    status = Column(String, nullable=False, default="queued")
    result_path = Column(String, nullable=True)
    report_directory = Column(String, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    fx_rate = Column(Float, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    summary = Column(Text, nullable=True)

    tenant = relationship("Tenant", backref="jobs")
