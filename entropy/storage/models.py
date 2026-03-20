"""
SQLAlchemy models for Entropy — maps to PostgreSQL + TimescaleDB schema.

Tables:
- repos: tracked repositories
- module_entropy: time-series entropy scores (TimescaleDB hypertable)
- alerts: fired alert records
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Repo(Base):
    __tablename__ = "repos"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    path = Column(Text, nullable=False)
    language = Column(String(20), default="python")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_scan_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    entropy_records = relationship("ModuleEntropy", back_populates="repo", cascade="all, delete-orphan")
    alert_records = relationship("AlertRecord", back_populates="repo", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "path": self.path,
            "language": self.language,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_scan_at": self.last_scan_at.isoformat() if self.last_scan_at else None,
        }


class ModuleEntropy(Base):
    """
    Time-series table for entropy scores per module.
    In production, this becomes a TimescaleDB hypertable on the ``time`` column.
    """

    __tablename__ = "module_entropy"

    id = Column(Integer, primary_key=True, autoincrement=True)
    time = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    repo_id = Column(UUID(as_uuid=True), ForeignKey("repos.id"), nullable=False, index=True)
    module_path = Column(Text, nullable=False, index=True)
    entropy_score = Column(Float, nullable=False)
    knowledge_score = Column(Float)
    dep_score = Column(Float)
    churn_score = Column(Float)
    age_score = Column(Float)
    blast_radius = Column(Integer)
    bus_factor = Column(Integer)
    trend_per_month = Column(Float)

    # Extra detail fields
    authors_active = Column(Integer)
    authors_total = Column(Integer)
    months_since_refactor = Column(Float)
    churn_commits = Column(Integer)
    refactor_commits = Column(Integer)

    # Relationship
    repo = relationship("Repo", back_populates="entropy_records")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "time": self.time.isoformat() if self.time else None,
            "repo_id": str(self.repo_id),
            "module_path": self.module_path,
            "entropy_score": self.entropy_score,
            "knowledge_score": self.knowledge_score,
            "dep_score": self.dep_score,
            "churn_score": self.churn_score,
            "age_score": self.age_score,
            "blast_radius": self.blast_radius,
            "bus_factor": self.bus_factor,
            "trend_per_month": self.trend_per_month,
            "authors_active": self.authors_active,
            "authors_total": self.authors_total,
            "months_since_refactor": self.months_since_refactor,
        }


class AlertRecord(Base):
    __tablename__ = "alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repo_id = Column(UUID(as_uuid=True), ForeignKey("repos.id"), nullable=False, index=True)
    module_path = Column(Text)
    severity = Column(String(20))  # CRITICAL / HIGH / WATCH
    message = Column(Text)
    fired_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    resolved = Column(Boolean, default=False)

    # Relationship
    repo = relationship("Repo", back_populates="alert_records")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "repo_id": str(self.repo_id),
            "module_path": self.module_path,
            "severity": self.severity,
            "message": self.message,
            "fired_at": self.fired_at.isoformat() if self.fired_at else None,
            "resolved": self.resolved,
        }
