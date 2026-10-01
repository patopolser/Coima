"""
src/api/routers/graph.py - Entity-centric neighbourhood graph endpoints.

GET /api/graph/company/{cuit}        graph around one provider.
GET /api/graph/unit/{code}           graph around one contracting unit.
GET /api/graph/authorizer/{name}     graph around one authorizer.

The graphs themselves are built in services/graph_service.py (shared with the
MCP server); these handlers only map query params and translate a missing
anchor into a 404. Query params let the caller toggle won-only, bids, earning
labels, the contact network and a date range (on the process opening date).
Nodes carry the data the frontend needs (e.g. Process.source_url for
click-through, Provider.cuit / Unit.code / Authorizer.name for navigation).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from src.i18n.translator import t

from ..dependencies import neo4j_driver
from ..locale import get_locale
from ..services import graph_service

router = APIRouter(prefix="/api/graph", tags=["graph"])


def _build(fn, *args, **kwargs) -> Optional[dict]:
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/company/{cuit}")
def graph_company(
    cuit: str,
    won_only: bool = Query(False, description="Only processes awarded to this provider"),
    show_bids: bool = Query(True, description="Include processes the provider bid on"),
    show_earnings: bool = Query(False, description="Label won edges with the awarded amount"),
    show_contacts: bool = Query(True, description="Include the contact/shared-provider network"),
    date_from: Optional[str] = Query(None, description="ISO date; filter by process opening date"),
    date_to: Optional[str] = Query(None, description="ISO date; filter by process opening date"),
    driver=Depends(neo4j_driver),
    locale: str = Depends(get_locale),
):
    """
    Return a configurable provider-centric graph.

    Response: `{ nodes: [...], edges: [...] }`. Edges use cytoscape-native
    `source`/`target`. Provider-to-Process edges carry `kind` ('WON' or
    'BID') and, when `show_earnings` is set, an amount `label`.
    """
    result = _build(
        graph_service.company_graph, driver, cuit,
        won_only=won_only, show_bids=show_bids, show_earnings=show_earnings,
        show_contacts=show_contacts, date_from=date_from, date_to=date_to,
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=t("errors.provider_not_found", locale, cuit=cuit),
        )
    return result


@router.get("/unit/{code:path}")
def graph_unit(
    code: str,
    show_earnings: bool = Query(False, description="Label won edges with the awarded amount"),
    date_from: Optional[str] = Query(None, description="ISO date; filter by process opening date"),
    date_to: Optional[str] = Query(None, description="ISO date; filter by process opening date"),
    driver=Depends(neo4j_driver),
    locale: str = Depends(get_locale),
):
    """
    Return a contracting-unit-centric graph: the unit, the processes it
    manages, and the providers awarded those processes.
    """
    result = _build(
        graph_service.unit_graph, driver, code,
        show_earnings=show_earnings, date_from=date_from, date_to=date_to,
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=t("errors.unit_not_found", locale, code=code),
        )
    return result


@router.get("/authorizer/{name:path}")
def graph_authorizer(
    name: str,
    show_earnings: bool = Query(False, description="Label won edges with the awarded amount"),
    date_from: Optional[str] = Query(None, description="ISO date; filter by process opening date"),
    date_to: Optional[str] = Query(None, description="ISO date; filter by process opening date"),
    driver=Depends(neo4j_driver),
    locale: str = Depends(get_locale),
):
    """
    Return an authorizer-centric graph: the authorizer, the processes whose
    contractual documents they signed, and the providers awarded those.
    """
    result = _build(
        graph_service.authorizer_graph, driver, name,
        show_earnings=show_earnings, date_from=date_from, date_to=date_to,
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=t("errors.authorizer_not_found", locale, name=name),
        )
    return result
