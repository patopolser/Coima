"""
process_page.py - Main process detail page parser for
VistaPreviaPliegoCiudadano.aspx.

Extracts the process header, organization (SAF), contracting unit (UOC), line
items, procurement requests, penalties, GDE documents and invited providers
(CDI/LPU), and detects the postback targets for the offer/award sub-pages.
"""

from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup, Tag

from config import settings
from scraper.models import (
    ContractingUnitModel,
    GDEDocumentModel,
    InvitesRelProps,
    LineItemModel,
    OrganizationModel,
    PenaltyModel,
    ProcurementRequestModel,
    ProcessModel,
    ProviderModel,
)
from utils.logging_config import get_logger
from utils.parsers import (
    clean_cuit,
    clean_text,
    extract_saf_code,
    normalize_currency,
    parse_bool,
    parse_date,
    parse_datetime,
    parse_float,
    parse_int,
    split_uoc,
)

logger = get_logger(__name__)


class ProcessPageResult:
    """Structured output from parsing a single process detail page."""

    def __init__(self) -> None:
        self.process: ProcessModel | None = None
        self.organization: OrganizationModel | None = None
        self.contracting_unit: ContractingUnitModel | None = None
        self.line_items: list[LineItemModel] = []
        self.procurement_requests: list[ProcurementRequestModel] = []
        self.penalties: list[PenaltyModel] = []
        self.gde_documents: list[GDEDocumentModel] = []
        self.invites: list[InvitesRelProps] = []
        self.invited_providers: list[ProviderModel] = []
        # Sub-page postback targets (__EVENTTARGET) or direct URLs.
        self.offers_target: str | None = None
        self.oc_targets: list[str] = []
        self.oca_target: str | None = None
        self.opening_act_targets: list[str] = []     # CONTRAT.AR: actas de apertura
        self.dictamen_targets: list[str] = []        # CONTRAT.AR: dictámenes de preadjudicación
        self.contract_summaries: dict[str, dict] = {}  # target -> {status, currency}
        # Captured ASP.NET form state to allow postbacks.
        self.viewstate_data: dict[str, str] = {}


class ProcessPageParser:
    """Parses a VistaPreviaPliegoCiudadano page into a :class:`ProcessPageResult`."""

    def __init__(
        self,
        html: str,
        process_number: str,
        source_url: str,
        override_status: str | None = None,
    ) -> None:
        self._soup = BeautifulSoup(html, "lxml")
        self._process_number = process_number
        self._source_url = source_url
        self._override_status = override_status
        self._result = ProcessPageResult()

    def parse(self) -> ProcessPageResult:
        """Parse the page and return the populated result."""
        soup = self._soup
        result = self._result
        process_number = self._process_number

        # Capture viewstate so we can post back to subpages.
        for field in ["__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"]:
            el = soup.find("input", {"name": field})
            if el:
                result.viewstate_data[field] = el.get("value", "")

        # 1. Process header.
        raw_status = self._override_status or self._field("Estado") or self._field("Estado del proceso")
        status_key = raw_status

        type_match = re.search(r"-([A-Z]+)\d{2}$", process_number)
        proc_type_code = type_match.group(1) if type_match else None

        result.process = ProcessModel(
            process_number=process_number,
            file_number=self._field("Número de expediente"),
            descriptive_name=self._field("Nombre descriptivo del proceso") or self._field("Nombre del proceso"),
            object_of_procurement=self._field("Objeto de la contratación"),
            selection_procedure=self._field("Procedimiento de selección"),
            process_type_code=proc_type_code,
            modality=self._field("Modalidad"),
            stage=self._field("Etapa"),
            scope=self._field("Alcance"),
            quotation_type=self._field("Tipo de cotización"),
            award_type=self._field("Tipo de adjudicación"),
            generated_document_type=self._field("Tipo documento que genera el proceso"),
            status=status_key,
            reception_address=self._field("Lugar de recepción de documentación física") or self._field("Domicilio de presentación"),
            offer_maintenance_days=parse_int(self._field("Plazo mantenimiento de la oferta") or self._field("Mantenimiento de oferta")),
            requires_payment=parse_bool(self._field("Requiere pago")),
            generates_resources=parse_bool(self._field("Genera recursos")),
            external_financing=parse_bool(self._field("Financiamiento Externo")),
            accepts_extension=parse_bool(self._field("Acepta prórroga")),
            accepts_price_adjustment=parse_bool(self._field("Redeterminación de precios")),
            scheduled_portal_publish_date=parse_datetime(self._field("Fecha y hora estimada de publicación en el portal")),
            official_gazette_publish_date=parse_datetime(self._field("Publicación en Boletín Oficial")),
            inquiry_start_date=parse_datetime(self._field("Fecha y hora inicio de consultas")),
            inquiry_end_date=parse_datetime(self._field("Fecha y hora final de consultas")),
            days_to_publish=parse_int(self._field("Cantidad de días a publicar")),
            opening_date=parse_datetime(
                self._field("Fecha y hora acto de apertura")
                or self._field("Fecha y hora del acto de apertura")
                or self._field("Fecha y hora de apertura")
                or self._field("Fecha de apertura")
                or self._field("Apertura de ofertas")
            ),
            contracting_system=self._field("Sistema de Contratación"),
            financial_advance=self._field("Anticipo Financiero"),
            requires_repair_fund=parse_bool(self._field("Requiere fondo de reparo")),
            includes_price_improvement=parse_bool(self._field("Incluye mejora de propuestas en Apertura")),
            source_url=self._source_url,
            scraped_at=datetime.utcnow(),
        )

        # Legal framework: may be a list of items.
        result.process.legal_framework = (
            self._extract_list_items(soup, "Encuadre legal")
            or self._extract_list_items(soup, "Marco legal")
            or self._extract_list_items(soup, "Marco normativo")
            or []
        )

        # Currencies.
        result.process.currencies = [
            normalize_currency(c) or c for c in (self._extract_list_items(soup, "Moneda") or [])
        ]

        # 2 & 3. Organization (SAF) and Contracting unit (UOC).
        uoc_raw = self._field("Unidad Operativa de Contrataciones")
        uoc_code, uoc_name = split_uoc(uoc_raw)

        # Prefer an explicit SAF from page labels. Only ContractingUnit keeps a
        # SAF fallback from the process number; Organization stays unknown until
        # an explicit SAF or OC/OCA buyer data is found.
        saf_raw = (
            self._field("Servicio Administrativo Financiero")
            or self._field("Jurisdicción")
            or self._field("Jurisdiccion")
        )
        saf_name: str | None = None
        explicit_saf_code: int | None = None
        if saf_raw and " - " in saf_raw:
            saf_head, saf_name = saf_raw.split(" - ", 1)
            explicit_saf_code = parse_int(saf_head)
            saf_name = clean_text(saf_name)
        else:
            explicit_saf_code = parse_int(saf_raw) if saf_raw else None

        # comprar process numbers start with the SAF code, so it doubles as a
        # fallback. contratar numbers start with the portal's UOC code (a
        # different registry), so no fallback applies: the SAF arrives later
        # from the contract (CON) page buyer block.
        if explicit_saf_code is not None:
            uoc_saf_code = explicit_saf_code
        elif settings.source == "contratar":
            uoc_saf_code = None
        else:
            uoc_saf_code = extract_saf_code(process_number)

        if explicit_saf_code is not None:
            result.organization = OrganizationModel(saf_code=explicit_saf_code, name=saf_name)

        if uoc_code:
            result.contracting_unit = ContractingUnitModel(
                code=uoc_code.strip() if uoc_code else "",
                name=uoc_name.strip() if uoc_name else "",
                saf_code=uoc_saf_code,
            )

        # 4. Participating / confirmed offer counts. comprar exposes them as
        # labeled fields; contratar as inline headings ("Constructores
        # Participantes: 3" / "Propuestas confirmadas: 1").
        result.process.participating_providers_count = parse_int(
            self._field("Cantidad de proveedores participantes")
            or self._field("Proveedores participantes")
            or self._inline_count(r"Constructores\s+Participantes")
        )
        result.process.confirmed_offers_count = parse_int(
            self._field("Cantidad de ofertas confirmadas")
            or self._field("Ofertas confirmadas")
            or self._inline_count(r"Propuestas\s+confirmadas")
        )

        # 5-10. Collection sections.
        result.line_items = self._parse_line_items()
        result.procurement_requests = self._parse_procurement_requests()
        result.penalties = self._parse_penalties()
        result.gde_documents = self._parse_gde_documents()
        if proc_type_code in ("CDI", "LPU", "LPR"):
            result.invited_providers, result.invites = self._parse_invited_providers()

        # 11. Sub-page links.
        result.offers_target = self._find_postback_target(soup, r"Ver cuadro comparativo")
        result.oc_targets = self._find_all_postback_targets(soup, r"-(?:OC|CON)\d{2}$")
        result.oca_target = (
            self._find_postback_target(soup, r"-OCA\d{2}$")
            or self._find_postback_target_by_id(soup, r"OCAsPliego.*lnkNumero")
        )
        # CONTRAT.AR execution stage: opening acts and pre-award opinions. The
        # anchors carry a direct URL inside WebForm_PostBackOptions, which
        # _extract_anchor_target resolves.
        result.opening_act_targets = self._find_all_postback_targets_by_id(soup, r"lnkVerActaApertura")
        result.dictamen_targets = self._find_all_postback_targets_by_id(soup, r"lnkVerDictamen")

        # Extract status/currency metadata for OC targets from the
        # adjudications table on the process page.
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue
            headers = [clean_text(th.get_text()) or "" for th in rows[0].find_all(["th", "td"])]
            col = self._col_index(headers)

            if "estado" in col and "moneda" in col:
                for row in rows[1:]:
                    cells = row.find_all(["td", "th"])
                    if not cells:
                        continue
                    anchor = row.find("a")
                    if anchor:
                        target = self._extract_anchor_target(anchor)
                        if target:
                            status_val = clean_text(cells[col["estado"]].get_text()) if col.get("estado") is not None and col["estado"] < len(cells) else None
                            currency_val = normalize_currency(clean_text(cells[col["moneda"]].get_text())) if col.get("moneda") is not None and col["moneda"] < len(cells) else None
                            result.contract_summaries[target] = {
                                "status": status_val,
                                "currency": currency_val,
                            }

        return result

    def _field(self, label_text: str, scope: Tag | None = None) -> str | None:
        """Find a labeled field value (case-insensitive).

        Preference order: a `<label>` whose text contains `label_text` and
        its sibling/row value; then inline `<span>/<b>/<strong>` labels;
        then adjacent table cells.
        """
        scope = scope or self._soup
        prefix = label_text.lower().strip()

        # 1. <label> elements (most reliable).
        for lbl in scope.find_all("label"):
            lbl_clean = clean_text(lbl.get_text()) or ""
            if prefix in lbl_clean.lower():
                sib = lbl.find_next_sibling()
                if sib:
                    val = clean_text(sib.get_text())
                    if val:
                        return val
                row = lbl.find_parent("tr")
                if row:
                    cells = row.find_all(["td", "th"])
                    for i, cell in enumerate(cells):
                        if cell.find("label") == lbl and i + 1 < len(cells):
                            return clean_text(cells[i + 1].get_text())

        # 2. Other inline elements.
        for el in scope.find_all(string=True):
            clean_str = clean_text(el)
            if clean_str and prefix in clean_str.lower():
                parent = el.parent
                if not parent:
                    continue
                if parent.name in ("span", "strong", "b"):
                    sibling = parent.find_next_sibling(["p", "span", "div"])
                    if sibling:
                        val = clean_text(sibling.get_text())
                        if val:
                            return val
                row = parent.find_parent("tr")
                if row:
                    cells = row.find_all(["td", "th"])
                    for i, cell in enumerate(cells):
                        cell_text = clean_text(cell.get_text()) or ""
                        if prefix in cell_text.lower() and i + 1 < len(cells):
                            return clean_text(cells[i + 1].get_text())
                sibling = parent.find_next_sibling(["td", "span", "div", "p"])
                if sibling:
                    val = clean_text(sibling.get_text())
                    if val:
                        return val
        return None

    def _inline_count(self, label_pattern: str) -> str | None:
        """Extract a count rendered inline as "<label>: N" (contratar headings)."""
        regex = re.compile(label_pattern + r"\s*:\s*(\d+)", re.I)
        for el in self._soup.find_all(string=regex):
            m = regex.search(el)
            if m:
                return m.group(1)
        return None

    def _parse_line_items(self) -> list[LineItemModel]:
        """Parse the Renglones table."""
        soup = self._soup
        items: list[LineItemModel] = []

        table = self._find_table_with_keywords(soup, ["rengl", "cantidad", "descrip"])
        if not table:
            table = self._find_table_with_keywords(soup, ["n°", "cantidad", "descrip"])
        if not table:
            table = self._find_table_with_keywords(soup, ["nº", "cantidad", "descrip"])
        if not table:
            # CONTRAT.AR "Detalle de obras": one row per renglón with the
            # official budget subtotal instead of quantity/description columns.
            table = self._find_table_with_keywords(soup, ["rengl", "objeto del gasto", "subtotal"])
        if not table:
            return items

        rows = table.find_all("tr")
        if len(rows) < 2:
            return items

        headers = [clean_text(th.get_text()) or "" for th in rows[0].find_all(["th", "td"])]
        col = self._col_index(headers)

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue

            def _cell(key: str) -> str | None:
                idx = col.get(key)
                return clean_text(cells[idx].get_text()) if idx is not None and idx < len(cells) else None

            line_number_raw = (
                _cell("número")
                or _cell("renglón")
                or _cell("nro")
                or _cell("n°")
                or _cell("nº")
            )
            line_number = parse_int(line_number_raw)
            if line_number is None:
                continue

            quantity_raw = _cell("cantidad")
            quantity = None
            unit_of_measure = _cell("unidad de medida") or _cell("u/m") or _cell("um")

            if quantity_raw:
                parts = quantity_raw.strip().split(" ", 1)
                quantity = parse_float(parts[0])
                if len(parts) > 1 and not unit_of_measure:
                    unit_of_measure = parts[1].strip()

            items.append(LineItemModel(
                process_number=self._process_number,
                line_number=line_number,
                expenditure_object=_cell("objeto del gasto") or _cell("clasificador"),
                catalog_code=_cell("código del ítem") or _cell("código ítem") or _cell("código"),
                description=_cell("descripc") or _cell("denominac") or _cell("frente de obra"),
                quantity=quantity,
                unit_of_measure=unit_of_measure,
                subtotal=parse_float(_cell("subtotal")),
                observations=_cell("observac"),
                specifications=_cell("especificac"),
                delivery_details=_cell("entrega"),
                is_grouped_item=parse_bool(_cell("agrupado")),
            ))

        return items

    def _parse_procurement_requests(self) -> list[ProcurementRequestModel]:
        """Parse the Solicitudes de Contratación (SCO) table."""
        soup = self._soup
        requests_list: list[ProcurementRequestModel] = []

        section = self._find_section(soup, r"[Ss]olicitud[es]* de [Cc]ontratación|SCO")
        if section is None:
            return requests_list

        table = section.find_next("table")
        if table is None:
            return requests_list

        rows = table.find_all("tr")
        if len(rows) < 2:
            return requests_list

        headers = [clean_text(th.get_text()) or "" for th in rows[0].find_all(["th", "td"])]
        col = self._col_index(headers)

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue

            def _cell(key: str) -> str | None:
                idx = col.get(key)
                return clean_text(cells[idx].get_text()) if idx is not None and idx < len(cells) else None

            req_number = _cell("número de solicitud") or _cell("nro. solicitud") or _cell("solicitud")
            if not req_number:
                continue

            requests_list.append(ProcurementRequestModel(
                request_number=req_number,
                process_number=self._process_number,
                status=_cell("estado"),
                executing_unit=_cell("unidad ejecutora") or _cell("unidad solicitante"),
                category=_cell("rubro"),
                urgency_type=_cell("tipo de urgencia") or _cell("urgencia"),
                created_at=parse_date(_cell("fecha de creación") or _cell("fecha")),
            ))

        return requests_list

    def _parse_penalties(self) -> list[PenaltyModel]:
        """Parse penalty clauses."""
        soup = self._soup
        penalties: list[PenaltyModel] = []

        section = self._find_section(soup, r"[Pp]enalidades|[Mm]ultas y penalidades")
        if section is None:
            return penalties

        table = section.find_next("table")
        if table is None:
            return penalties

        for i, row in enumerate(table.find_all("tr")[1:], start=1):
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            penalties.append(PenaltyModel(
                process_number=self._process_number,
                number=i,
                description=clean_text(cells[-1].get_text()),
            ))

        return penalties

    def _parse_gde_documents(self) -> list[GDEDocumentModel]:
        """Parse GDE documents attached to the process."""
        soup = self._soup
        docs: list[GDEDocumentModel] = []

        section = self._find_section(soup, r"[Dd]ocumentos|[Aa]ctos administrativos")
        if section is None:
            return docs

        table = section.find_next("table")
        if table is None:
            return docs

        rows = table.find_all("tr")
        if len(rows) < 2:
            return docs

        headers = [clean_text(th.get_text()) or "" for th in rows[0].find_all(["th", "td"])]
        col = self._col_index(headers)

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue

            def _cell(key: str) -> str | None:
                idx = col.get(key)
                return clean_text(cells[idx].get_text()) if idx is not None and idx < len(cells) else None

            gde_number = _cell("número gde") or _cell("número de documento") or _cell("número")
            if not gde_number:
                continue

            raw_type = _cell("documento") or _cell("tipo") or _cell("tipo de documento") or ""
            doc_type = raw_type or None

            docs.append(GDEDocumentModel(
                gde_number=gde_number,
                process_number=self._process_number,
                document_type=doc_type,
                special_number=_cell("número especial") or _cell("número de resolución"),
                linked_at=parse_date(_cell("fecha de vinculación") or _cell("fecha")),
                status=_cell("estado"),
            ))

        return docs

    def _parse_invited_providers(self) -> tuple[list[ProviderModel], list[InvitesRelProps]]:
        """Parse the 'Selección de proveedores' section (CDI/LPU)."""
        soup = self._soup
        providers: list[ProviderModel] = []
        invites: list[InvitesRelProps] = []

        section = self._find_section(soup, r"[Ss]elección de proveedores|Proveedores invitados")
        if section is None:
            return providers, invites

        table = section.find_next("table")
        if table is None:
            return providers, invites

        rows = table.find_all("tr")
        if len(rows) < 2:
            return providers, invites

        headers = [clean_text(th.get_text()) or "" for th in rows[0].find_all(["th", "td"])]
        col = self._col_index(headers)

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue

            def _cell(key: str) -> str | None:
                idx = col.get(key)
                return clean_text(cells[idx].get_text()) if idx is not None and idx < len(cells) else None

            cuit_raw = _cell("cuit")
            if not cuit_raw:
                continue

            cuit = clean_cuit(cuit_raw)
            if not cuit:
                continue

            providers.append(ProviderModel(
                cuit=cuit,
                business_name=_cell("razón social") or _cell("nombre"),
                sipro_status=_cell("estado"),
            ))
            invites.append(InvitesRelProps(process_number=self._process_number, provider_cuit=cuit))

        return providers, invites

    @staticmethod
    def _find_section(soup: BeautifulSoup, pattern: str) -> Tag | None:
        """Find the first heading element matching the regex pattern."""
        regex = re.compile(pattern, re.I)
        for tag_name in ("h1", "h2", "h3", "h4", "h5", "h6", "div", "span", "td", "th"):
            el = soup.find(tag_name, string=regex)
            if el:
                return el
        return None

    @classmethod
    def _find_postback_target(cls, soup: BeautifulSoup, text_pattern: str) -> str | None:
        """Find the first <a> whose text matches and extract its postback target."""
        regex = re.compile(text_pattern, re.I)
        a = soup.find("a", text=regex)
        if not a:
            for el in soup.find_all("a"):
                if regex.search(clean_text(el.get_text()) or ""):
                    a = el
                    break
        if a:
            return cls._extract_anchor_target(a)
        return None

    @classmethod
    def _find_postback_target_by_id(cls, soup: BeautifulSoup, id_pattern: str) -> str | None:
        """Find the first <a> whose id matches and return its navigation target."""
        regex = re.compile(id_pattern, re.I)
        for el in soup.find_all("a", id=True):
            el_id = el.get("id", "") or ""
            if regex.search(el_id):
                return cls._extract_anchor_target(el)
        return None

    @classmethod
    def _find_all_postback_targets(cls, soup: BeautifulSoup, text_pattern: str) -> list[str]:
        """Find all <a> whose text matches and extract their navigation targets."""
        regex = re.compile(text_pattern, re.I)
        targets: list[str] = []
        for a in soup.find_all("a"):
            if regex.search(clean_text(a.get_text()) or ""):
                target = cls._extract_anchor_target(a)
                if target and target not in targets:
                    targets.append(target)
        return targets

    @classmethod
    def _find_all_postback_targets_by_id(cls, soup: BeautifulSoup, id_pattern: str) -> list[str]:
        """Find all <a> whose id matches and extract their navigation targets."""
        regex = re.compile(id_pattern, re.I)
        targets: list[str] = []
        for a in soup.find_all("a", id=True):
            if regex.search(a.get("id", "") or ""):
                target = cls._extract_anchor_target(a)
                if target and target not in targets:
                    targets.append(target)
        return targets

    @staticmethod
    def _extract_anchor_target(a: Tag) -> str | None:
        """Resolve a navigation target from an anchor (postback or direct URL)."""
        href = (a.get("href", "") or "").strip()

        # WebForm_PostBackOptions often embeds a quoted relative URL, e.g.
        # /OC/VerDocumento... (comprar) or /EVALUACIONOFERTA/GenerarActa...
        # (contratar).
        m_url = re.search(r"[\"'](/[A-Za-z]+/[^\"']+\.aspx\?[^\"']*)[\"']", href)
        if m_url:
            return m_url.group(1)

        # Some pages expose direct document URLs without postback.
        if href and not href.lower().startswith("javascript:"):
            if "VerDocumentoContractualCiudadano.aspx" in href or "VistaPreviaOrdenCompraAbiertaCiudadano.aspx" in href:
                return href

        m = re.search(r"__doPostBack\('([^']+)'", href)
        if m:
            return m.group(1)

        # Fallback: construct a postback target from the element id.
        el_id = a.get("id", "")
        if el_id:
            return el_id.replace("_", "$", 1).replace("ctl00_", "ctl00$").replace("_CPH1_", "$CPH1$")

        return None

    @staticmethod
    def _col_index(headers: list[str]) -> dict[str, int]:
        """Build a keyword-to-column-index map for a table header row."""
        keywords = [
            # Common
            "número", "nro", "n°", "nº", "descripc", "denominac", "cantidad", "unidad", "u/m", "um",
            "precio", "monto", "total", "moneda", "observac", "especificac",
            # Line items specific
            "objeto del gasto", "clasificador",
            "código del ítem", "código ítem", "código",
            "frente de obra", "subtotal",
            # SCO
            "solicitud", "nro. solicitud", "estado", "unidad ejecutora",
            "unidad solicitante", "rubro", "urgencia", "tipo de urgencia",
            "fecha de creación", "fecha",
            # Provider
            "cuit", "razón social", "nombre",
            # GDE
            "tipo", "tipo de documento", "número gde", "número de documento", "documento",
            "número especial", "número de resolución", "fecha de vinculación",
        ]
        index: dict[str, int] = {}
        for i, header in enumerate(headers):
            lower = (header or "").lower().strip()
            for kw in keywords:
                if kw in lower and kw not in index:
                    index[kw] = i
        return index

    @staticmethod
    def _extract_list_items(soup: BeautifulSoup, label: str) -> list[str]:
        """Collect <li> texts or comma- or <br>-separated values next to a label."""
        label_el = soup.find(string=re.compile(re.escape(label), re.I))
        if not label_el:
            return []
        parent = label_el.parent
        sibling = parent.find_next_sibling() if parent else None
        if sibling is None:
            return []
        items = sibling.find_all("li")
        if items:
            return [clean_text(li.get_text()) for li in items if clean_text(li.get_text())]

        brs = sibling.find_all("br")
        if brs:
            html_str = str(sibling)
            parts = re.split(r"<br\s*/?>", html_str, flags=re.I)
            cleaned = []
            for p in parts:
                fragment_soup = BeautifulSoup(f"<span>{p}</span>", "lxml")
                val = clean_text(fragment_soup.get_text())
                if val:
                    cleaned.append(val)
            return cleaned

        raw = clean_text(sibling.get_text()) or ""
        return [v.strip() for v in raw.split(",") if v.strip()]

    @staticmethod
    def _find_table_with_keywords(soup: BeautifulSoup, keywords: list[str]) -> Tag | None:
        """Find a table whose header row contains all specified keywords."""
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue
            header_text = rows[0].get_text().lower()
            if all(kw in header_text for kw in keywords):
                return table
        return None
