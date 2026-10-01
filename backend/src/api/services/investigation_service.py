"""
src/api/services/investigation_service.py - Investigation CRUD over SQLite.

Cases, subjects, notes and reports written by AI agents through the MCP server.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from ..database.sqlite import (
    Investigation,
    InvestigationNote,
    InvestigationReport,
    InvestigationSubject,
)
from ..schemas.investigation import (
    InvestigationDetail,
    InvestigationSummary,
    NoteSchema,
    ReportSchema,
    SubjectSchema,
)

logger = logging.getLogger(__name__)


def _inv_to_summary(inv: Investigation) -> InvestigationSummary:
    return InvestigationSummary(
        id=inv.id,
        title=inv.title,
        status=inv.status,
        created_at=inv.created_at,
        updated_at=inv.updated_at,
        subjects=[
            SubjectSchema(
                type=s.type, id=s.subject_id, name=s.name or "", detail_url=s.detail_url
            )
            for s in inv.subjects
        ],
    )


def _inv_to_detail(inv: Investigation) -> InvestigationDetail:
    return InvestigationDetail(
        id=inv.id,
        title=inv.title,
        status=inv.status,
        created_at=inv.created_at,
        updated_at=inv.updated_at,
        context_snapshot=json.loads(inv.context_snapshot or "{}"),
        subjects=[
            SubjectSchema(
                type=s.type, id=s.subject_id, name=s.name or "", detail_url=s.detail_url
            )
            for s in inv.subjects
        ],
        notes=[
            NoteSchema(id=n.id, created_at=n.created_at, text=n.text) for n in inv.notes
        ],
        reports=[
            ReportSchema(id=r.id, type=r.type, content=r.content, created_at=r.created_at)
            for r in inv.reports
        ],
    )


def _now() -> str:
    return datetime.now().isoformat()


def _generate_id(prefix: str = "inv") -> str:
    ts = datetime.now().strftime("%Y%m%d%H%M")
    return f"{prefix}_{ts}_{uuid.uuid4().hex[:6]}"


def list_investigations(
    db: Session,
    status: Optional[str] = None,
    search: Optional[str] = None,
) -> list[InvestigationSummary]:
    q = db.query(Investigation)
    if status:
        q = q.filter(Investigation.status == status)
    invs = q.order_by(Investigation.updated_at.desc()).all()

    if search:
        sl = search.lower()
        invs = [
            i for i in invs
            if sl in i.title.lower()
            or any(sl in (s.name or "").lower() or sl in s.subject_id.lower() for s in i.subjects)
        ]

    return [_inv_to_summary(i) for i in invs]


def get_investigation(db: Session, inv_id: str) -> Optional[InvestigationDetail]:
    inv = db.get(Investigation, inv_id)
    return _inv_to_detail(inv) if inv else None


def create_investigation(
    db: Session,
    title: str,
    subjects: list,
    context_snapshot: dict,
) -> InvestigationDetail:
    now = _now()
    inv = Investigation(
        id=_generate_id("inv"),
        title=title,
        status="open",
        created_at=now,
        updated_at=now,
        context_snapshot=json.dumps(context_snapshot),
    )
    db.add(inv)
    db.flush()

    for s in subjects:
        db.add(InvestigationSubject(
            investigation_id=inv.id,
            type=s.type,
            subject_id=s.id,
            name=s.name,
            detail_url=getattr(s, "detail_url", None),
        ))

    db.commit()
    db.refresh(inv)
    return _inv_to_detail(inv)


def delete_investigation(db: Session, inv_id: str) -> bool:
    inv = db.get(Investigation, inv_id)
    if not inv:
        return False
    db.delete(inv)
    db.commit()
    return True


def set_status(db: Session, inv_id: str, status: str) -> Optional[InvestigationDetail]:
    inv = db.get(Investigation, inv_id)
    if not inv:
        return None
    inv.status = status
    inv.updated_at = _now()
    db.commit()
    db.refresh(inv)
    return _inv_to_detail(inv)


def add_subject(db: Session, inv_id: str, req: SubjectSchema) -> Optional[InvestigationDetail]:
    inv = db.get(Investigation, inv_id)
    if not inv:
        return None
    # Deduplicate against the existing subjects on (type, id).
    for s in inv.subjects:
        if s.type == req.type and s.subject_id == req.id:
            return _inv_to_detail(inv)
    db.add(InvestigationSubject(
        investigation_id=inv_id,
        type=req.type,
        subject_id=req.id,
        name=req.name,
        detail_url=req.detail_url,
    ))
    inv.updated_at = _now()
    db.commit()
    db.refresh(inv)
    return _inv_to_detail(inv)


def add_note(db: Session, inv_id: str, text: str) -> Optional[InvestigationDetail]:
    inv = db.get(Investigation, inv_id)
    if not inv:
        return None
    db.add(InvestigationNote(
        id=_generate_id("note"),
        investigation_id=inv_id,
        text=text,
        created_at=_now(),
    ))
    inv.updated_at = _now()
    db.commit()
    db.refresh(inv)
    return _inv_to_detail(inv)


def add_report(
    db: Session,
    inv_id: str,
    report_type: str,
    content: str,
) -> Optional[InvestigationReport]:
    inv = db.get(Investigation, inv_id)
    if not inv:
        return None
    report = InvestigationReport(
        id=_generate_id("rep"),
        investigation_id=inv_id,
        type=report_type,
        content=content,
        created_at=_now(),
    )
    db.add(report)
    inv.updated_at = _now()
    db.commit()
    return report
