"""
dictamen_page.py - CONTRAT.AR pre-award opinion (dictamen) parser for
PreAdjudicarVisualizarDictamenCiudadano.aspx.

Extracts, from a single dictamen page:

  * Header context: issue date, recommended winner and pre-award total, offers
    count, legal framework and budget imputation.
  * The pre-adjudication grid (committee's recommended winner per renglón) and
    the secondary-offers grid (merit-ordered runners-up).
  * Discarded bidders: per rejected provider, the per-requirement evaluation
    reasons (technical / economic / administrative) and free-text justification.
  * The evaluation committee from the DevExpress signers grid.

The page also exposes the opening date, used as a fallback for the process
opening_date.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from bs4 import BeautifulSoup, Tag

from utils.logging_config import get_logger
from utils.parsers import (
    clean_cuit,
    clean_text,
    normalize_currency,
    normalize_name,
    parse_date,
    parse_datetime,
    parse_float,
    parse_int,
)

logger = get_logger(__name__)


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


class DictamenEvaluator:
    """One signer/evaluator of the pre-award opinion.

    `username` is the portal user name from the signers grid (a raw CUIT when
    no username is exposed).
    """

    def __init__(self, username: str, role: str | None, status: str | None) -> None:
        self.username = username
        self.role = role
        self.status = status


class DictamenPreAdjudication:
    """One recommended-award row, from the pre-adjudication or secondary grid."""

    def __init__(self) -> None:
        self.provider_name: str | None = None
        self.group: str | None = None
        self.line_number: int | None = None
        self.alternative_number: int | None = None
        self.merit_order: int | None = None
        self.is_primary: bool = True
        self.quantity: float | None = None
        self.unit_of_measure: str | None = None
        self.unit_price: float | None = None
        self.total_per_line: float | None = None
        self.currency: str | None = None


class DictamenRejection:
    """One discarded bidder with the committee's reasons and justification."""

    def __init__(self) -> None:
        self.provider_name: str | None = None
        self.provider_cuit: str | None = None
        self.reasons: list[str] = []
        self.justification: str | None = None


class DictamenPageResult:
    """Structured output of a dictamen page."""

    def __init__(self) -> None:
        self.evaluators: list[DictamenEvaluator] = []
        self.opening_datetime: datetime | None = None
        self.issue_date: datetime | None = None
        self.pre_awarded_to: str | None = None
        self.pre_award_total: float | None = None
        self.currency: str | None = None
        self.offers_count: int | None = None
        self.legal_framework: str | None = None
        self.budget_imputation: str | None = None
        self.pre_adjudications: list[DictamenPreAdjudication] = []
        self.rejections: list[DictamenRejection] = []


class DictamenPageParser:
    """Parses a CONTRAT.AR dictamen page into a :class:`DictamenPageResult`."""

    def __init__(self, html: str) -> None:
        self._soup = BeautifulSoup(html, "lxml")

    def parse(self) -> DictamenPageResult:
        result = DictamenPageResult()
        result.evaluators = self._parse_evaluators()
        result.opening_datetime = self._parse_opening_datetime()
        result.issue_date = self._parse_date_field(self._span("lblFechaPublicacionTitulo"))
        result.pre_awarded_to = self._span("lblRazonSocial")
        result.pre_award_total, currency_from_total = self._parse_amount(
            self._span("lblCantPrecioTotalPreAdjudicacion")
        )
        result.currency = currency_from_total or normalize_currency(self._span("lblMoneda"))
        result.offers_count = parse_int(self._span("lblNumeroOfertasPresentadas"))
        result.legal_framework = self._span("txtEncuadre") or self._textarea("txtEncuadre")
        result.budget_imputation = self._span("txtImputacion") or self._textarea("txtImputacion")
        result.pre_adjudications = self._parse_pre_adjudications()
        result.rejections = self._parse_rejections()
        logger.info(
            "Parsed dictamen: %d evaluators, %d pre-adjudications, %d rejections.",
            len(result.evaluators), len(result.pre_adjudications), len(result.rejections),
        )
        return result

    # -- Header field helpers -------------------------------------------------

    def _span(self, id_suffix: str) -> str | None:
        """Return the cleaned text of the first span whose id ends with `id_suffix`."""
        el = self._soup.find("span", id=re.compile(re.escape(id_suffix) + r"$"))
        return clean_text(el.get_text()) if el else None

    def _textarea(self, id_suffix: str) -> str | None:
        el = self._soup.find("textarea", id=re.compile(re.escape(id_suffix) + r"$"))
        return clean_text(el.get_text()) if el else None

    @staticmethod
    def _parse_date_field(value: str | None) -> datetime | None:
        """Parse a date or datetime field into a datetime (date-only at midnight)."""
        dt = parse_datetime(value)
        if dt:
            return dt
        d = parse_date(value)
        return datetime(d.year, d.month, d.day) if d else None

    @staticmethod
    def _parse_amount(value: str | None) -> tuple[float | None, str | None]:
        """Split an "8.694.426,61 ARS" style string into (amount, currency)."""
        if not value:
            return None, None
        amount = parse_float(value)
        m = re.search(r"[A-Za-z$]{2,}\s*$", value.strip())
        currency = normalize_currency(m.group(0)) if m else None
        return amount, currency

    # -- Grid helpers ---------------------------------------------------------

    @staticmethod
    def _header_columns(table: Tag) -> list[str]:
        """Return the logical column captions of a DevExpress grid header.

        DevExpress renders each header caption inside a nested element, so the
        raw cells repeat; consecutive duplicates are collapsed to recover the
        one-caption-per-data-column order.
        """
        header = table.find("tr", id=re.compile(r"DXHeadersRow", re.I))
        if not header:
            return []
        captions: list[str] = []
        for cell in header.find_all(["td", "th"]):
            text = " ".join(cell.get_text(" ").split())
            if not text:
                continue
            if captions and captions[-1] == text:
                continue
            captions.append(text)
        return captions

    @staticmethod
    def _col(captions: list[str], *keywords: str) -> int | None:
        """Index of the first caption containing any keyword (accent-insensitive)."""
        for idx, caption in enumerate(captions):
            norm = _strip_accents(caption).lower()
            if any(_strip_accents(kw).lower() in norm for kw in keywords):
                return idx
        return None

    @staticmethod
    def _data_rows(table: Tag) -> list[list[str]]:
        rows: list[list[str]] = []
        for row in table.find_all("tr", id=re.compile(r"DXDataRow\d+$", re.I)):
            rows.append([" ".join(c.get_text(" ").split()) for c in row.find_all("td")])
        return rows

    @staticmethod
    def _cell(row: list[str], idx: int | None) -> str | None:
        if idx is None or idx >= len(row):
            return None
        return clean_text(row[idx])

    @staticmethod
    def _split_quantity(value: str | None) -> tuple[float | None, str | None]:
        """Split "1,00 UNIDAD" into (1.0, "UNIDAD")."""
        if not value:
            return None, None
        m = re.match(r"\s*([\d.,]+)\s*(.*)$", value)
        if not m:
            return None, None
        return parse_float(m.group(1)), (clean_text(m.group(2)) or None)

    # -- Pre-adjudication -----------------------------------------------------

    def _parse_pre_adjudications(self) -> list[DictamenPreAdjudication]:
        rows: list[DictamenPreAdjudication] = []
        # Primary recommendation grid: ...cabeceraDictamenPreAdjudicacion<n>_gvItems.
        primary = self._soup.find(
            "table", id=re.compile(r"cabeceraDictamenPreAdjudicacion\d*_gvItems_DXMainTable$", re.I)
        )
        rows.extend(self._parse_pre_adj_grid(primary, is_primary=True))
        # Secondary offers grid (merit-ordered runners-up).
        secondary = self._soup.find(
            "table", id=re.compile(r"gvOfertasSecundarias_DXMainTable$", re.I)
        )
        rows.extend(self._parse_pre_adj_grid(secondary, is_primary=False))
        return rows

    def _parse_pre_adj_grid(self, table: Tag | None, is_primary: bool) -> list[DictamenPreAdjudication]:
        if table is None:
            return []
        captions = self._header_columns(table)
        c_group = self._col(captions, "grupo")
        c_line = self._col(captions, "numero renglon", "renglon")
        c_alt = self._col(captions, "alternativa")
        c_merit = self._col(captions, "orden de merito", "merito")
        c_prov = self._col(captions, "pre adjudicatario", "adjudicatario")
        c_qty = self._col(captions, "cantidad")
        c_unit_price = self._col(captions, "precio unitario")
        c_currency = self._col(captions, "moneda")
        c_total = self._col(captions, "precio total")

        out: list[DictamenPreAdjudication] = []
        for row in self._data_rows(table):
            name = self._cell(row, c_prov)
            if not name:
                continue
            pa = DictamenPreAdjudication()
            pa.is_primary = is_primary
            pa.provider_name = name
            pa.group = self._cell(row, c_group)
            pa.line_number = parse_int(self._cell(row, c_line))
            pa.alternative_number = parse_int(self._cell(row, c_alt))
            pa.merit_order = parse_int(self._cell(row, c_merit))
            pa.quantity, pa.unit_of_measure = self._split_quantity(self._cell(row, c_qty))
            pa.unit_price = parse_float(self._cell(row, c_unit_price))
            pa.total_per_line = parse_float(self._cell(row, c_total))
            pa.currency = normalize_currency(self._cell(row, c_currency))
            out.append(pa)
        return out

    # -- Rejections -----------------------------------------------------------

    def _parse_rejections(self) -> list[DictamenRejection]:
        out: list[DictamenRejection] = []
        for grid in self._soup.find_all(
            "table", id=re.compile(r"gvEvaluacionDescartada_DXMainTable$", re.I)
        ):
            prefix = re.sub(r"_gvEvaluacionDescartada_DXMainTable$", "", grid.get("id", ""))
            rej = DictamenRejection()
            rej.provider_name, rej.provider_cuit = self._rejected_provider(prefix)
            rej.justification = self._rejection_justification(prefix)
            rej.reasons = self._rejection_reasons(grid)
            if rej.provider_name or rej.provider_cuit or rej.reasons:
                out.append(rej)
        return out

    def _rejected_provider(self, prefix: str) -> tuple[str | None, str | None]:
        """Read "<business name> <11-digit CUIT>" from the block's lblProveedor."""
        el = self._soup.find("span", id=re.compile(re.escape(prefix) + r"_lblProveedor$"))
        if el is None:
            el = self._soup.find("span", id=re.compile(re.escape(prefix) + r".*lblProveedor$"))
        text = clean_text(el.get_text()) if el else None
        if not text:
            return None, None
        m = re.search(r"(\d{11})\s*$", text.replace("-", ""))
        cuit = clean_cuit(m.group(1)) if m else None
        name = clean_text(re.sub(r"[\d\-]{8,}\s*$", "", text)) or text
        return name, cuit

    def _rejection_justification(self, prefix: str) -> str | None:
        el = self._soup.find("textarea", id=re.compile(re.escape(prefix) + r".*txtJustificacionProveedor$"))
        if el is None:
            el = self._soup.find("span", id=re.compile(re.escape(prefix) + r".*txtJustificacionProveedor$"))
        return clean_text(el.get_text()) if el else None

    def _rejection_reasons(self, grid: Tag) -> list[str]:
        captions = self._header_columns(grid)
        c_desc = self._col(captions, "descripcion")
        c_tec = self._col(captions, "tecnica")
        c_eco = self._col(captions, "economica")
        c_adm = self._col(captions, "administrativa")
        reasons: list[str] = []
        for row in self._data_rows(grid):
            requirement = self._cell(row, c_desc) or ""
            for area, idx in (("Tecnica", c_tec), ("Economica", c_eco), ("Administrativa", c_adm)):
                reason = self._cell(row, idx)
                if reason:
                    prefix = f"{requirement} :: " if requirement else ""
                    reasons.append(f"{prefix}[{area}] {reason}")
        return reasons

    # -- Evaluators (signers grid) --------------------------------------------

    def _parse_evaluators(self) -> list[DictamenEvaluator]:
        evaluators: list[DictamenEvaluator] = []
        seen: set[str] = set()

        # Several DevExpress grids share the gvItems naming (pre-adjudication
        # amounts, merit order, signers); the signers grid is the one whose
        # header row reads "Nombre Usuario / Cargo / Estado".
        table = None
        for candidate in self._soup.find_all("table", id=re.compile(r"DXMainTable$", re.I)):
            header = candidate.find("tr", id=re.compile(r"DXHeadersRow", re.I))
            header_text = (header.get_text(" ") if header else "").lower()
            if "nombre usuario" in header_text:
                table = candidate
                break
        if table is None:
            return evaluators

        for row in table.find_all("tr", id=re.compile(r"DXDataRow\d+$", re.I)):
            cells = [clean_text(c.get_text()) or "" for c in row.find_all("td")]
            if not cells or not cells[0]:
                continue
            username = normalize_name(cells[0])
            if not username or username in seen:
                continue
            seen.add(username)
            evaluators.append(DictamenEvaluator(
                username=username,
                role=cells[1] if len(cells) > 1 and cells[1] else None,
                status=cells[2] if len(cells) > 2 and cells[2] else None,
            ))

        return evaluators

    def _parse_opening_datetime(self) -> datetime | None:
        """Read the opening datetime from the header info table or labeled span."""
        labeled = self._span("lblFechaApertuta") or self._span("lblFechaHoraApertura")
        dt = parse_datetime(labeled)
        if dt:
            return dt
        label = self._soup.find(string=re.compile(r"Fecha de Apertura", re.I))
        if not label:
            return None
        cell = label.find_parent("td")
        if cell:
            sibling = cell.find_next_sibling("td")
            if sibling:
                return parse_datetime(clean_text(sibling.get_text()))
        return None
