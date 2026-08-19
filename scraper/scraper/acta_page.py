"""
acta_page.py - CONTRAT.AR opening act parser for
GenerarActaAperturaBastrap.aspx.

The opening act publishes the real opening date/time and one row per
confirmed proposal with its guarantee details ("Lista de las propuestas"
table: bidder, CUIT, confirmation date, quoted currency, total price and
guarantee type/form/amount). It complements the comparative table, which on
CONTRAT.AR omits submission dates and guarantees.
"""

from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup, Tag

from utils.logging_config import get_logger
from utils.parsers import (
    clean_cuit,
    clean_text,
    normalize_currency,
    parse_date,
    parse_datetime,
    parse_float,
)

logger = get_logger(__name__)


class ActaProposal:
    """One confirmed proposal row from the opening act."""

    def __init__(self) -> None:
        self.cuit: str | None = None
        self.business_name: str | None = None
        self.submitted_at: datetime | None = None
        self.currency: str | None = None
        self.total_amount: float | None = None
        self.guarantee_type: str | None = None
        self.guarantee_form: str | None = None
        self.guarantee_amount: float | None = None


class ActaPageResult:
    """Structured output of an opening act page."""

    def __init__(self) -> None:
        self.opening_datetime: datetime | None = None
        self.proposals: list[ActaProposal] = []


class ActaPageParser:
    """Parses a CONTRAT.AR opening act page into an :class:`ActaPageResult`."""

    def __init__(self, html: str) -> None:
        self._soup = BeautifulSoup(html, "lxml")

    def parse(self) -> ActaPageResult:
        result = ActaPageResult()
        result.opening_datetime = self._parse_opening_datetime()
        result.proposals = self._parse_proposals()
        logger.info(
            "Parsed opening act: opening=%s, proposals=%d",
            result.opening_datetime, len(result.proposals),
        )
        return result

    def _label_value(self, label_text: str) -> str | None:
        """Value next to the first non-empty `<label>` matching `label_text`."""
        pattern = re.compile(rf"^{re.escape(label_text.lower())}\b", re.I)
        for lbl in self._soup.find_all("label"):
            lt = (clean_text(lbl.get_text()) or "").lower()
            if pattern.search(lt):
                sib = lbl.find_next_sibling()
                if sib:
                    val = clean_text(sib.get_text())
                    if val:
                        return val
        return None

    def _parse_opening_datetime(self) -> datetime | None:
        """Combine the "Fecha" and "Hora" fields of the "Apertura" block."""
        fecha = self._label_value("Fecha")
        hora = self._label_value("Hora")
        if not fecha:
            return None
        if hora:
            dt = parse_datetime(f"{fecha} {hora}")
            if dt:
                return dt
            m = re.search(r"(\d{1,2}):(\d{2})", hora)
            if m:
                d = parse_date(fecha)
                if d:
                    hour = int(m.group(1))
                    if re.search(r"p\.?\s*m", hora, re.I) and hour < 12:
                        hour += 12
                    return datetime(d.year, d.month, d.day, hour, int(m.group(2)))
        d = parse_date(fecha)
        return datetime(d.year, d.month, d.day) if d else None

    def _parse_proposals(self) -> list[ActaProposal]:
        """Parse the "Lista de las propuestas" table."""
        proposals: list[ActaProposal] = []
        table = self._find_table(["c.u.i.t", "garant"])
        if table is None:
            table = self._find_table(["cuit", "garant"])
        if table is None:
            return proposals

        rows = table.find_all("tr")
        if len(rows) < 2:
            return proposals

        headers = [clean_text(c.get_text()) or "" for c in rows[0].find_all(["th", "td"])]
        col = self._col_map(headers)

        for row in rows[1:]:
            cells = [clean_text(c.get_text()) or "" for c in row.find_all(["td", "th"])]
            if not cells:
                continue

            def _c(key: str, _cells=cells) -> str | None:
                idx = col.get(key)
                return _cells[idx] if idx is not None and idx < len(_cells) else None

            cuit = clean_cuit(_c("c.u.i.t") or _c("cuit"))
            if not cuit:
                continue

            p = ActaProposal()
            p.cuit = cuit
            p.business_name = _c("razón social") or _c("nombre")
            raw_confirmation = _c("fecha de confirmación") or ""
            p.submitted_at = parse_datetime(raw_confirmation)
            if p.submitted_at is None:
                d = parse_date(raw_confirmation)
                p.submitted_at = datetime(d.year, d.month, d.day) if d else None
            p.currency = normalize_currency(_c("moneda"))
            p.total_amount = parse_float(_c("precio total"))
            p.guarantee_type = _c("tipo de garantía")
            p.guarantee_form = _c("forma de la garantía") or _c("forma de garantía")
            p.guarantee_amount = parse_float(_c("monto de la garantía") or _c("monto de garantía"))
            proposals.append(p)

        return proposals

    def _find_table(self, keywords: list[str]) -> Tag | None:
        for table in self._soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue
            header_text = rows[0].get_text(separator=" ").lower()
            if all(kw in header_text for kw in keywords):
                return table
        return None

    @staticmethod
    def _col_map(headers: list[str]) -> dict[str, int]:
        keywords = [
            "razón social", "nombre",
            "c.u.i.t", "cuit",
            "fecha de confirmación",
            "moneda",
            "precio total",
            "tipo de garantía",
            "forma de la garantía", "forma de garantía",
            "monto de la garantía", "monto de garantía",
        ]
        index: dict[str, int] = {}
        for i, header in enumerate(headers):
            lower = (header or "").lower().strip()
            for kw in keywords:
                if kw in lower and kw not in index:
                    index[kw] = i
        return index
