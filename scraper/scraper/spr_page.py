"""
spr_page.py - Solicitud de Provisión (SPR) page parser for
VistaPreviaSolicitudProvisionCiudadano.aspx.

Extracts the provision request header, the awarded provider, the item lines,
and the authorizers (with their DNI, which OC/OCA pages omit) plus their
AUTHORIZED_BY relationship properties.
"""

from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup, Tag

from scraper.models import (
    AuthorizedByRelProps,
    AuthorizerModel,
    ProviderModel,
    ProvisionRequestLineModel,
    ProvisionRequestModel,
)
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


class SPRPageResult:
    """All data extracted from a single SPR page."""

    def __init__(self) -> None:
        self.provision_request: ProvisionRequestModel | None = None
        self.provider: ProviderModel | None = None
        self.lines: list[ProvisionRequestLineModel] = []
        self.authorizers: list[AuthorizerModel] = []
        self.authorizations: list[tuple[str, AuthorizedByRelProps]] = []


class SPRPageParser:
    """Parses a Solicitud de Provisión page into an :class:`SPRPageResult`."""

    def __init__(self, html: str, oca_number: str, source_url: str) -> None:
        self._soup = BeautifulSoup(html, "lxml")
        self._oca_number = oca_number
        self._source_url = source_url
        self._result = SPRPageResult()

    def parse(self) -> SPRPageResult:
        """Parse the page and return the populated result."""
        soup = self._soup
        result = self._result

        # 1. Header block.
        request_number = (
            self._field("Número de solicitud de provisión")
            or self._field("Número de solicitud")
            or self._field("Solicitud de provisión")
        )
        if not request_number:
            logger.warning("Could not extract SPR number from: %s", self._source_url)
            return result

        status_key = self._field("Estado")

        # 2. Información Básica block.
        saf_code = parse_int(self._field("Servicio Administrativo Financiero") or self._field("Código SAF"))
        saf_name = self._field("Nombre SAF") or self._field("Organismo")
        requesting_unit = self._field("Unidad solicitante")
        descriptive_name = self._field("Nombre de la solicitud de provisión") or self._field("Nombre")
        object_description = self._field("Objeto de la solicitud de provisión") or self._field("Objeto")

        total_amount_raw = self._extract_importe_total_text(soup)
        total_amount = parse_float(total_amount_raw or self._field("Importe total") or self._field("Total"))
        currency: str | None = normalize_currency(
            self._extract_importe_currency(total_amount_raw) or self._field("Moneda")
        )

        result.provision_request = ProvisionRequestModel(
            request_number=request_number,
            oca_number=self._oca_number,
            process_number=self._field("Número de proceso de compra") or self._field("Proceso"),
            file_number=self._field("Número de expediente") or self._field("Expediente"),
            created_at=parse_datetime(self._field("Fecha creación") or self._field("Fecha de creación")),
            status=status_key,
            saf_code=saf_code,
            saf_name=saf_name,
            requesting_unit=requesting_unit,
            descriptive_name=descriptive_name,
            object_description=object_description,
            total_amount=total_amount,
            currency=currency,
            source_url=self._source_url,
            scraped_at=datetime.utcnow(),
        )

        # 3. Awarded provider.
        cuit = clean_cuit(self._field("CUIT"))
        if not cuit:
            m = re.search(r"\b(\d{2}-\d{8}-\d)\b", soup.get_text())
            cuit = clean_cuit(m.group(1)) if m else None

        if cuit:
            result.provision_request.provider_cuit = cuit
            result.provider = ProviderModel(
                cuit=cuit,
                business_name=self._field("Razón social") or self._field("Nombre"),
                sipro_entity_id=parse_int(self._field("Número de ente") or self._field("Ente SIPRO")),
                address=self._field("Domicilio") or self._field("Dirección"),
                postal_code=self._field("Código postal") or self._field("CP"),
                city=self._field("Localidad") or self._field("Ciudad"),
                province=self._field("Provincia"),
                phone=self._field("Teléfono"),
                fax=self._field("Fax"),
                email=self._field("Correo electrónico") or self._field("Email"),
                sipro_status=self._field("Estado SIPRO") or self._field("Estado proveedor"),
            )

        # 4. Item lines.
        result.lines, derived_currency = self._parse_lines(request_number)
        if not result.provision_request.currency and derived_currency:
            result.provision_request.currency = derived_currency

        # 5. Authorizers.
        result.authorizers, result.authorizations = self._parse_authorizers(request_number)

        logger.info(
            "Parsed SPR %s: %d lines, %d authorizers.",
            request_number, len(result.lines), len(result.authorizers),
        )
        return result

    def _field(self, label_text: str, scope: Tag | None = None) -> str | None:
        """Find a labeled field value (case-insensitive)."""
        scope = scope or self._soup
        prefix = clean_text(label_text).lower()
        for el in scope.find_all(string=True):
            clean_str = clean_text(el)
            if clean_str and prefix in clean_str.lower():
                parent = el.parent
                if not parent:
                    continue
                if parent.name in ("label", "span", "strong", "b"):
                    sibling = parent.find_next_sibling(["p", "span", "div"])
                    if sibling:
                        return clean_text(sibling.get_text())
                row = parent.find_parent("tr")
                if row:
                    cells = row.find_all(["td", "th"])
                    for i, cell in enumerate(cells):
                        val = clean_text(cell.get_text())
                        if val and prefix in val.lower() and i + 1 < len(cells):
                            return clean_text(cells[i + 1].get_text())
        return None

    def _parse_lines(
        self, request_number: str,
    ) -> tuple[list[ProvisionRequestLineModel], str | None]:
        """Parse the items table. Returns `(lines, currency_if_found)`."""
        soup = self._soup
        lines: list[ProvisionRequestLineModel] = []
        found_currency: str | None = None

        section = self._find_section(soup, r"[Íí]tems|[Rr]englones|[Aa]rtículos")
        table = (section.find_next("table") if section else None) or self._find_table_with_keywords(
            soup, ["precio unitario", "cantidad"]
        )
        if table is None:
            return lines, found_currency

        rows = table.find_all("tr")
        if len(rows) < 2:
            return lines, found_currency

        headers = [clean_text(th.get_text()) or "" for th in rows[0].find_all(["th", "td"])]
        col = self._col_index_lines(headers)

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            cell_texts = [clean_text(c.get_text()) or "" for c in cells]

            def _c(key: str) -> str | None:
                idx = col.get(key)
                return cell_texts[idx] if idx is not None and idx < len(cell_texts) else None

            line_number = parse_int(_c("número renglón") or _c("renglón") or _c("nro") or cell_texts[0])
            if line_number is None:
                continue

            currency = normalize_currency(_c("moneda"))
            if currency and not found_currency:
                found_currency = currency

            lines.append(ProvisionRequestLineModel(
                request_number=request_number,
                line_number=line_number,
                alternative_number=parse_int(_c("alternativa")),
                catalog_code=_c("código ítem") or _c("código"),
                description=_c("descripción"),
                quantity=parse_float(_c("cantidad a comprar") or _c("cantidad")),
                unit_of_measure=_c("unidad de medida") or _c("u/m"),
                unit_price=parse_float(_c("precio unitario")),
                currency=currency,
                total_price=parse_float(_c("precio total") or _c("total")),
            ))

        return lines, found_currency

    def _parse_authorizers(
        self, request_number: str,
    ) -> tuple[list[AuthorizerModel], list[tuple[str, AuthorizedByRelProps]]]:
        """Parse the Autorizador/es block (SPR pages include DNI)."""
        soup = self._soup
        authorizers: list[AuthorizerModel] = []
        rels: list[tuple[str, AuthorizedByRelProps]] = []

        section = self._find_section(soup, r"[Aa]utorizador|[Ff]irmante")
        table = (section.find_next("table") if section else None) or self._find_table_with_keywords(
            soup, ["autorizador", "rol"]
        )
        if table is None:
            return authorizers, rels

        rows = table.find_all("tr")
        if len(rows) < 2:
            return authorizers, rels

        headers = [clean_text(th.get_text()) or "" for th in rows[0].find_all(["th", "td"])]
        col = self._col_index_authorizers(headers)

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            cell_texts = [clean_text(c.get_text()) or "" for c in cells]

            def _c(key: str) -> str | None:
                idx = col.get(key)
                return cell_texts[idx] if idx is not None and idx < len(cell_texts) else None

            first_name = _c("nombre") or _c("autorizador")
            last_name = _c("apellido")
            full_name = normalize_name(" ".join(v for v in [first_name, last_name] if v))
            if not full_name:
                continue

            # DNI: format "DNI 23753535" or just the number.
            dni_raw = _c("dni") or _c("número de documento") or _c("documento")
            doc_type: str | None = None
            doc_number: str | None = None
            if dni_raw:
                m = re.match(r"(DNI|LC|LE|CI)?\s*(\d+)", dni_raw.upper())
                if m:
                    doc_type = m.group(1) or "DNI"
                    doc_number = m.group(2)

            authorizers.append(AuthorizerModel(
                full_name=full_name,
                document_type=doc_type,
                document_number=doc_number,
            ))

            raw_authorized_at = _c("fecha") or _c("fecha de autorización")
            authorized_at = parse_datetime(raw_authorized_at)
            if authorized_at is None:
                parsed_d = parse_date(raw_authorized_at)
                if parsed_d is not None:
                    authorized_at = datetime.combine(parsed_d, datetime.min.time())

            rels.append((
                request_number,
                AuthorizedByRelProps(
                    authorizer_name=full_name,
                    role=_c("rol") or _c("cargo"),
                    executing_unit=_c("unidad ejecutora") or _c("unidad"),
                    authorized_at=authorized_at,
                ),
            ))

        return authorizers, rels

    @staticmethod
    def _find_section(soup: BeautifulSoup, pattern: str) -> Tag | None:
        """Find the first heading element matching the regex pattern."""
        regex = re.compile(pattern, re.I)
        for tag_name in ("h1", "h2", "h3", "h4", "h5", "h6", "div", "span", "td", "th"):
            el = soup.find(tag_name, string=regex)
            if el:
                return el
        return None

    @staticmethod
    def _find_table_with_keywords(soup: BeautifulSoup, keywords: list[str]) -> Tag | None:
        """Find a table whose header row contains all keywords."""
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue
            header_text = rows[0].get_text().lower()
            if all(kw in header_text for kw in keywords):
                return table
        return None

    @staticmethod
    def _extract_importe_total_text(soup: BeautifulSoup) -> str | None:
        """Get the raw total amount string from the SPR totals card."""
        el = soup.find("span", id=re.compile(r"lblImporteTotal$", re.I))
        if el:
            return clean_text(el.get_text())
        return None

    @staticmethod
    def _extract_importe_currency(raw_total: str | None) -> str | None:
        """Extract a three-letter currency code from the totals string."""
        if not raw_total:
            return None
        m = re.search(r"\b([A-Z]{3})\b", raw_total)
        return m.group(1) if m else None

    @staticmethod
    def _col_index_lines(headers: list[str]) -> dict[str, int]:
        """Map item-line column keywords to their header index."""
        keywords = [
            "número renglón", "renglón", "renglon", "nro",
            "alternativa",
            "código ítem", "código",
            "descripción",
            "cantidad a comprar", "cantidad",
            "unidad de medida", "u/m",
            "precio unitario",
            "moneda",
            "precio total", "total",
        ]
        index: dict[str, int] = {}
        for i, header in enumerate(headers):
            lower = (header or "").lower().strip()
            for kw in keywords:
                if kw in lower and kw not in index:
                    index[kw] = i
        return index

    @staticmethod
    def _col_index_authorizers(headers: list[str]) -> dict[str, int]:
        """Map authorizer column keywords to their header index."""
        keywords = [
            "nombre", "autorizador",
            "apellido",
            "dni", "número de documento", "documento",
            "rol", "cargo",
            "unidad ejecutora", "unidad",
            "fecha", "fecha de autorización",
        ]
        index: dict[str, int] = {}
        for i, header in enumerate(headers):
            lower = (header or "").lower().strip()
            for kw in keywords:
                if kw in lower and kw not in index:
                    index[kw] = i
        return index
