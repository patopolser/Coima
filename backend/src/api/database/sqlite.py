"""
src/api/database/sqlite.py - SQLAlchemy ORM models and database initialisation.

Stores detection runs, the findings cache, risk scores, and all investigation
data (subjects, notes, reports). An additive migration step
runs on every startup so new columns introduced after a deployment can be
added in place without dropping data.
"""

from __future__ import annotations

import os
from typing import Optional

from sqlalchemy import (
    Column, DateTime, ForeignKey, Integer, String, Text, create_engine, func, inspect, text,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship


class Base(DeclarativeBase):
    pass


class DetectionRun(Base):
    __tablename__ = "detection_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    tender_count = Column(Integer, nullable=False, default=0)
    config_snapshot = Column(Text)
    summary = Column(Text)
    status = Column(String, default="running", nullable=False)

    findings = relationship(
        "DetectionFinding", back_populates="run", cascade="all, delete-orphan"
    )
    risk_scores = relationship(
        "RiskScore", back_populates="run", cascade="all, delete-orphan"
    )


class DetectionFinding(Base):
    __tablename__ = "detection_findings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("detection_runs.id"), nullable=False, index=True)
    check_key = Column(String, nullable=False, index=True)
    data = Column(Text, nullable=False)

    run = relationship("DetectionRun", back_populates="findings")


class RiskScore(Base):
    __tablename__ = "risk_scores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("detection_runs.id"), nullable=False, index=True)
    cuit = Column(String, nullable=False, index=True)
    company = Column(String)
    score = Column(Integer, default=0)
    # JSON array of check keys. Legacy rows stored a CSV string; reads
    # transparently migrate either shape into a list.
    flags = Column(String)
    # entity_type lets non-provider entities (units, authorizers) share this
    # table with their own namespace.
    entity_type = Column(String, default="provider", nullable=False)
    base_score = Column(Integer, default=0)
    confidence = Column(Integer, default=0)
    evidence_breakdown = Column(Text)

    run = relationship("DetectionRun", back_populates="risk_scores")


class DetectionConfig(Base):
    __tablename__ = "detection_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    data = Column(Text, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Investigation(Base):
    __tablename__ = "investigations"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    status = Column(String, default="open", nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    context_snapshot = Column(Text, default="{}")

    subjects = relationship(
        "InvestigationSubject", back_populates="investigation",
        cascade="all, delete-orphan", order_by="InvestigationSubject.id"
    )
    notes = relationship(
        "InvestigationNote", back_populates="investigation",
        cascade="all, delete-orphan", order_by="InvestigationNote.created_at"
    )
    reports = relationship(
        "InvestigationReport", back_populates="investigation",
        cascade="all, delete-orphan", order_by="InvestigationReport.created_at"
    )


class InvestigationSubject(Base):
    __tablename__ = "investigation_subjects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    investigation_id = Column(
        String, ForeignKey("investigations.id"), nullable=False, index=True
    )
    type = Column(String, nullable=False)
    subject_id = Column(String, nullable=False)
    name = Column(String, default="")
    detail_url = Column(String)

    investigation = relationship("Investigation", back_populates="subjects")


class InvestigationNote(Base):
    __tablename__ = "investigation_notes"

    id = Column(String, primary_key=True)
    investigation_id = Column(
        String, ForeignKey("investigations.id"), nullable=False, index=True
    )
    text = Column(Text, nullable=False)
    created_at = Column(String, nullable=False)

    investigation = relationship("Investigation", back_populates="notes")


class InvestigationReport(Base):
    __tablename__ = "investigation_reports"

    id = Column(String, primary_key=True)
    investigation_id = Column(
        String, ForeignKey("investigations.id"), nullable=False, index=True
    )
    type = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(String, nullable=False)

    investigation = relationship("Investigation", back_populates="reports")


_engine = None


def init_db(sqlite_path: str):
    """Initialise the SQLite engine and create all tables. Call once on startup."""
    global _engine
    os.makedirs(os.path.dirname(os.path.abspath(sqlite_path)), exist_ok=True)
    _engine = create_engine(
        f"sqlite:///{sqlite_path}",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    Base.metadata.create_all(_engine)
    _migrate_additive(_engine)
    return _engine


# Columns added after the table first shipped. SQLite cannot add them via
# create_all on an existing table, so we ALTER any that are missing. All are
# nullable or defaulted, so this is safe to run on every startup.
_ADDITIVE_COLUMNS = {
    "risk_scores": {
        "entity_type": "VARCHAR DEFAULT 'provider'",
        "base_score": "INTEGER DEFAULT 0",
        "confidence": "INTEGER DEFAULT 0",
        "evidence_breakdown": "TEXT",
    },
}


def _migrate_additive(engine) -> None:
    """Add any missing columns to existing tables (idempotent, additive only)."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in _ADDITIVE_COLUMNS.items():
            if table not in existing_tables:
                continue
            present = {col["name"] for col in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in present:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def get_engine():
    if _engine is None:
        raise RuntimeError("SQLite engine not initialized. Call init_db() first.")
    return _engine


def get_session() -> Session:
    """Return a new SQLAlchemy session. The caller is responsible for closing it."""
    return Session(get_engine())
