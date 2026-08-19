"""
src/api/routers/investigations.py - Investigation CRUD plus SSE-streamed AI
chat and report generation.

The sync AI generators (Claude, Gemini, DeepSeek) run in a thread-pool
executor, feeding an asyncio.Queue that the async SSE generator drains. That
keeps FastAPI's event loop unblocked while the model thinks.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from src.i18n.translator import t

from ..dependencies import db_session
from ..locale import get_locale
from ..schemas.investigation import (
    AddNoteRequest,
    AddSubjectRequest,
    ChatRequest,
    CreateInvestigationRequest,
    InvestigationDetail,
    InvestigationSummary,
    ReportRequest,
    UpdateStatusRequest,
)
from ..services import investigation_service as svc
from ..services import detection_service
from ..services.config_service import get_detection_config
from ..services.scoring_service import build_check_meta, get_company_index, merge_legacy_meta

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/investigations", tags=["investigations"])

_SENTINEL = object()
_CONTEXT_ROWS_PER_CHECK = 50


def _not_found(locale: str):
    return HTTPException(status_code=404, detail=t("errors.investigation_not_found", locale))


def _get_detection_context(db: Session, locale: str):
    cfg = get_detection_config(db)
    weight_cfg = cfg.get("weights", {})
    check_meta = build_check_meta(weight_cfg, locale=locale)
    run = detection_service._get_latest_done_run(db)

    if run is None:
        return {}, [], check_meta, {}

    findings = detection_service.get_findings_for_run(db, run.id)
    risk_scores = detection_service.get_risk_scores_for_run(db, run.id)
    check_meta = merge_legacy_meta(check_meta, findings, weight_cfg, locale=locale)
    company_index = get_company_index(run.id, findings, risk_scores, check_meta)
    return findings, risk_scores, check_meta, company_index


def _slice_findings(rows: list, limit: int = _CONTEXT_ROWS_PER_CHECK) -> dict:
    return {
        "total": len(rows),
        "included": min(len(rows), limit),
        "rows": rows[:limit],
        "truncated": len(rows) > limit,
    }


def _find_tender_matches(process: str, findings: dict) -> dict:
    matches: dict = {}
    process_fields = ("process", "voided_process", "direct_process")
    for check_key, rows in findings.items():
        matched_rows = [
            row for row in rows
            if any(row.get(field) == process for field in process_fields)
        ]
        if matched_rows:
            matches[check_key] = _slice_findings(matched_rows)
    return matches


def _build_inv_context(inv: InvestigationDetail, db: Session, locale: str = "en") -> dict:
    """
    Build the investigation dict that AI clients expect, augmented with
    context from the latest detection run.
    """
    findings, risk_scores, check_meta, company_index = _get_detection_context(db, locale)

    context_snapshot: dict = {
        "risk_scores": {},
        "findings_summary": {},
        "findings_samples": {},
        "findings_totals": {},
        "tender_findings": {},
        "notes": [
            {"created_at": note.created_at, "text": note.text}
            for note in inv.notes
        ],
    }
    for subj in inv.subjects:
        if subj.type == "company":
            cuit = subj.id
            company_data = company_index.get(cuit)
            if not company_data:
                continue

            if company_data.get("risk_score"):
                context_snapshot["risk_scores"][cuit] = company_data["risk_score"]

            for check_key, rows in company_data.get("findings", {}).items():
                rows_list = list(rows)
                context_snapshot["findings_summary"].setdefault(cuit, {})[check_key] = len(rows_list)
                context_snapshot["findings_samples"].setdefault(cuit, {})[check_key] = rows_list[:_CONTEXT_ROWS_PER_CHECK]
                if len(rows_list) > _CONTEXT_ROWS_PER_CHECK:
                    context_snapshot["findings_totals"].setdefault(cuit, {})[check_key] = {
                        "total": len(rows_list),
                        "included": _CONTEXT_ROWS_PER_CHECK,
                    }
        elif subj.type == "tender":
            tender_matches = _find_tender_matches(subj.id, findings)
            if tender_matches:
                context_snapshot["tender_findings"][subj.id] = tender_matches

    return {
        "id": inv.id,
        "title": inv.title,
        "status": inv.status,
        "created_at": inv.created_at,
        "subjects": [{"type": s.type, "id": s.id, "name": s.name} for s in inv.subjects],
        "context_snapshot": context_snapshot,
        "chat_history": [
            {"role": m.role, "content": m.content}
            for m in inv.chat_history
        ],
        "_locale": locale,
    }


def _drop_current_user_message(inv_context: dict, user_message: str) -> dict:
    chat_history = inv_context.get("chat_history", [])
    if chat_history and chat_history[-1]["role"] == "user" and chat_history[-1]["content"] == user_message:
        inv_context = {**inv_context, "chat_history": chat_history[:-1]}
    return inv_context


def _build_ai_client(model: str, db: Session, locale: str):
    from src.ai.claude_client import ClaudeClient, CoimaTools
    from src.ai.deepseek_client import DeepSeekClient
    from src.ai.gemini_client import GeminiClient
    from ..config import get_settings

    settings = get_settings()
    findings, risk_scores, check_meta, company_index = _get_detection_context(db, locale)

    neo4j_config = {
        "uri": settings.neo4j_uri,
        "user": settings.neo4j_user,
        "password": settings.neo4j_password,
    }
    tools = CoimaTools(company_index, findings, neo4j_config)

    if model == "gemini":
        return GeminiClient(tools)
    if model == "deepseek":
        return DeepSeekClient(tools)
    return ClaudeClient(tools)


async def _stream_ai_generator(sync_gen, heartbeat_seconds: int = 15):
    """
    Wrap a synchronous AI generator in an asyncio-friendly async generator.
    Uses a thread plus queue to avoid blocking the event loop while the model
    is producing tokens.
    """
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def run_in_thread():
        try:
            for event in sync_gen:
                loop.call_soon_threadsafe(queue.put_nowait, event)
        except Exception as exc:
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "content": str(exc)})
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

    loop.run_in_executor(None, run_in_thread)

    waited = 0
    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
        except asyncio.TimeoutError:
            waited += heartbeat_seconds
            yield {"type": "heartbeat", "seconds": waited}
            continue
        if event is _SENTINEL:
            break
        yield event


@router.get("", response_model=List[InvestigationSummary])
def list_investigations(
    db: Session = Depends(db_session),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    return svc.list_investigations(db, status=status, search=search)


@router.post("", response_model=InvestigationDetail, status_code=201)
def create_investigation(
    body: CreateInvestigationRequest,
    db: Session = Depends(db_session),
):
    return svc.create_investigation(
        db,
        title=body.title,
        subjects=body.subjects,
        context_snapshot=body.context_snapshot,
    )


@router.get("/{investigation_id}", response_model=InvestigationDetail)
def get_investigation(
    investigation_id: str,
    db: Session = Depends(db_session),
    locale: str = Depends(get_locale),
):
    inv = svc.get_investigation(db, investigation_id)
    if inv is None:
        raise _not_found(locale)
    return inv


@router.get("/{investigation_id}/prompt")
def get_investigation_prompt(
    investigation_id: str,
    model: str = Query("deepseek"),
    db: Session = Depends(db_session),
    locale: str = Depends(get_locale),
):
    """Return the raw system prompt text and chat history for the given investigation and model."""
    inv = svc.get_investigation(db, investigation_id)
    if inv is None:
        raise _not_found(locale)

    inv_context = _build_inv_context(inv, db, locale)
    client = _build_ai_client(model, db, locale)

    if hasattr(client, "_build_system_prompt"):
        system_prompt = client._build_system_prompt(inv_context)
    else:
        system_prompt = json.dumps(inv_context, default=str)

    return {
        "system_prompt": system_prompt,
        "chat_history": inv_context.get("chat_history", [])
    }


@router.delete("/{investigation_id}", status_code=204)
def delete_investigation(
    investigation_id: str,
    db: Session = Depends(db_session),
    locale: str = Depends(get_locale),
):
    if not svc.delete_investigation(db, investigation_id):
        raise _not_found(locale)


@router.put("/{investigation_id}/status", response_model=InvestigationDetail)
def update_status(
    investigation_id: str,
    body: UpdateStatusRequest,
    db: Session = Depends(db_session),
    locale: str = Depends(get_locale),
):
    inv = svc.set_status(db, investigation_id, body.status)
    if inv is None:
        raise _not_found(locale)
    return inv


@router.post("/{investigation_id}/subjects", response_model=InvestigationDetail)
def add_subject(
    investigation_id: str,
    body: AddSubjectRequest,
    db: Session = Depends(db_session),
    locale: str = Depends(get_locale),
):
    inv = svc.add_subject(db, investigation_id, body)
    if inv is None:
        raise _not_found(locale)
    return inv


@router.post("/{investigation_id}/notes", response_model=InvestigationDetail)
def add_note(
    investigation_id: str,
    body: AddNoteRequest,
    db: Session = Depends(db_session),
    locale: str = Depends(get_locale),
):
    if not body.text.strip():
        raise HTTPException(status_code=400, detail=t("errors.note_empty", locale))
    inv = svc.add_note(db, investigation_id, body.text)
    if inv is None:
        raise _not_found(locale)
    return inv


@router.post("/{investigation_id}/chat")
async def chat(
    investigation_id: str,
    body: ChatRequest,
    db: Session = Depends(db_session),
    locale: str = Depends(get_locale),
):
    """
    Stream a chat response from Claude, Gemini or DeepSeek over Server-Sent
    Events.

    Each event is `data: <JSON>\\n\\n` with one of these `type`s:
      tool_use     the AI is calling a tool
      tool_result  the tool returned (preview-truncated)
      message      a text chunk from the AI
      error        an error occurred
      done         the stream finished
    """
    inv = svc.get_investigation(db, investigation_id)
    if inv is None:
        raise _not_found(locale)

    if not body.message.strip():
        raise HTTPException(status_code=400, detail=t("errors.message_empty", locale))

    svc.add_chat_message(db, investigation_id, "user", body.message)

    inv = svc.get_investigation(db, investigation_id)
    inv_context = _drop_current_user_message(_build_inv_context(inv, db, locale), body.message)
    client = _build_ai_client(body.model, db, locale)

    full_response: list[str] = []
    tool_calls: list[dict] = []

    async def event_stream():
        nonlocal full_response, tool_calls
        yield f"data: {json.dumps({'type': 'status', 'stage': 'backend_request_received'})}\n\n"
        async for event in _stream_ai_generator(client.chat(inv_context, body.message)):
            if event["type"] == "tool_use":
                tool_calls.append(event)
                yield f"data: {json.dumps({'type': 'tool_use', 'tool': event['tool'], 'input': event.get('input', {})})}\n\n"
            elif event["type"] == "tool_result":
                payload = {
                    "type": "tool_result",
                    "tool": event["tool"],
                    "result_preview": str(event.get("result", ""))[:1000],
                }
                if event["tool"].startswith("deepseek_nvidia"):
                    payload["result"] = event.get("result")
                yield f"data: {json.dumps(payload)}\n\n"
            elif event["type"] == "message":
                full_response.append(event["content"])
                yield f"data: {json.dumps({'type': 'message', 'content': event['content']})}\n\n"
            elif event["type"] == "error":
                yield f"data: {json.dumps({'type': 'error', 'content': event['content']})}\n\n"
            elif event["type"] == "heartbeat":
                yield f"data: {json.dumps({'type': 'status', 'stage': 'waiting_model', 'seconds': event.get('seconds', 0)})}\n\n"

        if full_response:
            content = "\n".join(full_response)
            svc.add_chat_message(
                db, investigation_id, "assistant", content,
                tool_calls=[{"name": tc["tool"], "input": tc.get("input")} for tc in tool_calls],
            )

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/{investigation_id}/reports")
async def generate_report(
    investigation_id: str,
    body: ReportRequest,
    db: Session = Depends(db_session),
    locale: str = Depends(get_locale),
):
    """
    Generate an investigation report using Claude, Gemini or DeepSeek over SSE.
    Same event shape as /chat, with the final `done` event carrying a
    `report_id` when one was persisted.
    """
    inv = svc.get_investigation(db, investigation_id)
    if inv is None:
        raise _not_found(locale)

    inv_context = _build_inv_context(inv, db, locale)

    client = _build_ai_client(body.model, db, locale)

    full_content: list[str] = []

    async def event_stream():
        yield f"data: {json.dumps({'type': 'status', 'stage': 'backend_request_received'})}\n\n"
        async for event in _stream_ai_generator(client.generate_report(inv_context, body.type)):
            if event["type"] == "tool_use":
                yield f"data: {json.dumps({'type': 'tool_use', 'tool': event['tool']})}\n\n"
            elif event["type"] == "tool_result":
                payload = {
                    "type": "tool_result",
                    "tool": event["tool"],
                    "result_preview": str(event.get("result", ""))[:1000],
                }
                if event["tool"].startswith("deepseek_nvidia"):
                    payload["result"] = event.get("result")
                yield f"data: {json.dumps(payload)}\n\n"
            elif event["type"] == "message":
                full_content.append(event["content"])
                yield f"data: {json.dumps({'type': 'content', 'content': event['content']})}\n\n"
            elif event["type"] == "error":
                yield f"data: {json.dumps({'type': 'error', 'content': event['content']})}\n\n"
            elif event["type"] == "heartbeat":
                yield f"data: {json.dumps({'type': 'status', 'stage': 'waiting_model', 'seconds': event.get('seconds', 0)})}\n\n"

        if full_content:
            content = "\n".join(full_content)
            report = svc.add_report(db, investigation_id, body.type, content)
            yield f"data: {json.dumps({'type': 'done', 'report_id': report.id if report else None})}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
