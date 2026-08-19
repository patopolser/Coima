"""OC and OCA detail page parser.

Parses two ASP.NET pages that share a structure:

* OC (Purchase Order): ``VerDocumentoContractualCiudadano.aspx?qs=<token>``
* OCA (Open Purchase Order): ``VistaPreviaOrdenCompraAbiertaCiudadano.aspx?qs=<token>``

Both yield a contractual document, the buyer organization, the awarded provider,
the awarded contract lines, and the authorizers. OCA pages additionally yield
SPR links and extension/prorroga summary fields.
"""

from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup, Tag

from config import settings
from scraper.models import (
    AuthorizedByRelProps,
    AuthorizerModel,
    ContractLineModel,
    ContractualDocumentModel,
    OrganizationModel,
    ProviderModel,
)
from utils.logging_config import get_logger
from utils.parsers import (
    clean_cuit,
    clean_text,
    make_absolute,
    normalize_currency,
    normalize_name,
    parse_date,
    parse_datetime,
    parse_float,
    parse_int,
)

logger = get_logger(__name__)


class OCPageResult:
    """All data extracted from a single OC or OCA page."""

    def __init__(self) -> None:
        self.document: ContractualDocumentModel | None = None
        self.provider: ProviderModel | None = None
        self.buyer: OrganizationModel | None = None
        self.buyer_contact: dict[str, str | None] = {}
        self.contract_lines: list[ContractLineModel] = []
        self.authorizers: list[AuthorizerModel] = []
        self.authorizations: list[tuple[str, AuthorizedByRelProps]] = []
        self.spr_urls: list[str] = []
        self.is_oca: bool = False


class OCPageParser:
    """Parses an OC or OCA detail page into an :class:`OCPageResult`."""

    def __init__(
        self,
        html: str,
        process_number: str,
        source_url: str,
        is_oca: bool = False,
    ) -> None:
        self._soup = BeautifulSoup(html, "lxml")
        self._process_number = process_number
        self._source_url = source_url
        self._is_oca = is_oca
        self._result = OCPageResult()
        self._result.is_oca = is_oca

    def parse(self) -> OCPageResult:
        """Parse the page and return the populated result."""
        soup = self._soup
        result = self._result
        is_oca = self._is_oca

        # 1. Document number.
        if is_oca:
            doc_number = self._label_field("Número Orden de compra abierta") or self._label_field("Número de OCA")
        else:
            doc_number = (
                self._label_field("Número Orden de compra")
                or self._label_field("Número de OC")
                or self._label_field("Número Contrato")
                or self._label_field("Número documento contractual")
                or self._general_document_number(soup)
            )

        if not doc_number:
            for lbl in soup.find_all("label"):
                lt = clean_text(lbl.get_text()) or ""
                if "número" in lt.lower() and ("orden de compra" in lt.lower() or lt.lower().startswith("número")):
                    sib = lbl.find_next_sibling()
                    if sib:
                        val = clean_text(sib.get_text())
                        if val and re.search(r"\d+(?:/\d+)?-\d+-(?:OC|OCA|CON)\d{2}", val, re.I):
                            doc_number = val
                            break

        if not doc_number:
            logger.warning("Could not extract document number from OC/OCA page: %s", self._source_url)
            return result

        contract_duration = (
            self._label_field("Duración del contrato:")
            or self._label_field("Duración del contrato")
            or self._label_field("Duración")
        )

        # 1b. Document type.
        document_type = self._label_field("Tipo", index=0)
        revision_type = None
        if is_oca:
            tipo_oca = soup.find("span", id=re.compile(r"lblTipoOCA$", re.I))
            valor_tipo_oca = soup.find("span", id=re.compile(r"lblValorTipoOCA$", re.I))
            document_type = (
                clean_text(tipo_oca.get_text()) if tipo_oca else None
            ) or (
                clean_text(valor_tipo_oca.get_text()) if valor_tipo_oca else None
            ) or document_type
        elif doc_number and re.search(r"-CON\d{2}$", doc_number, re.I):
            # On contratar contract pages the first "Tipo" is the revision
            # ("Original" / "Ampliación"), not the document class.
            if document_type and document_type.lower() in ("original", "ampliación", "ampliacion"):
                revision_type = document_type
            document_type = "Contrato"

        result.document = ContractualDocumentModel(
            document_number=doc_number,
            process_number=self._process_number,
            provider_cuit="",          # filled below from the provider block
            document_type=document_type,
            revision_type=revision_type,
            status=None,               # populated by main.py
            authorization_date=parse_date(self._label_field("Fecha autorización")),
            perfection_date=parse_date(self._label_field("Fecha perfeccionamiento") or self._label_field("Fecha de perfeccionamiento") or self._label_field("Fecha vinculación")),
            total_amount=self._parse_total_amount(soup),
            current_amount=self._span_value(soup, r"lblImporteVigente$"),
            variation_pct=self._span_value(soup, r"lblPorcentajeVariacion$"),
            award_act_number=clean_text(self._label_field("Número acto administrativo de adjudicación") or "") or None,
            currency=None,             # populated by main.py
            delivery_start_date=parse_date(self._label_field("Fecha inicio") or self._label_field("Fecha de inicio de entrega")),
            contract_duration=contract_duration,
            source_url=self._source_url,
            scraped_at=datetime.utcnow(),
        )

        # Extension/prorroga summary fields.
        result.document.max_extendable_amount = parse_float(self._get_val_from_summary_table(soup, r"Resumen solicitudes de ampliación", r"Monto máximo ampliable"))
        result.document.extension_currency = normalize_currency(self._get_val_from_summary_table(soup, r"Resumen solicitudes de ampliación", r"Moneda"))
        result.document.confirmed_extensions_count = parse_int(self._get_val_from_summary_table(soup, r"Resumen solicitudes de ampliación", r"Total ampliaciones confirmadas"))
        result.document.available_extension_amount = parse_float(self._get_val_from_summary_table(soup, r"Resumen solicitudes de ampliación", r"Monto disponible a ampliar"))
        result.document.available_extension_pct = parse_float(self._get_val_from_summary_table(soup, r"Resumen solicitudes de ampliación", r"Porcentaje disponible a ampliar"))

        result.document.max_extendable_periods = parse_float(self._get_val_from_summary_table(soup, r"Resumen solicitudes de prórroga", r"Cantidad máxima prorrogable"))
        result.document.extension_period_currency = normalize_currency(self._get_val_from_summary_table(soup, r"Resumen solicitudes de prórroga", r"Moneda"))
        result.document.available_extension_period_pct = parse_float(self._get_val_from_summary_table(soup, r"Resumen solicitudes de prórroga", r"Porcentaje disponible a prorrogar"))

        if not result.document.confirmed_extensions_count:
            result.document.confirmed_extensions_count = parse_int(self._span_field("Total ampliaciones confirmadas") or self._label_field("Total ampliaciones confirmadas"))

        # 2. Buyer block.
        result.buyer, result.buyer_contact = self._parse_buyer_block(soup)

        # 3. Awarded provider block.
        provider = self._parse_provider_block(soup)
        if provider:
            result.provider = provider
            result.document.provider_cuit = provider.cuit

        # 4. Contract lines.
        result.contract_lines = self._parse_contract_lines(soup, doc_number, is_oca)
        result.document.observations = self._parse_document_observations(soup)

        # 5. Authorizers.
        result.authorizers, result.authorizations = self._parse_authorizers(soup, doc_number)

        # 6. SPR links (OCA only).
        if is_oca:
            result.spr_urls = self._extract_spr_urls(soup)
            logger.debug("OCA %s: found %d SPR links.", doc_number, len(result.spr_urls))

        logger.info(
            "Parsed %s %s: %d contract lines, %d authorizers, %d SPRs.",
            "OCA" if is_oca else "OC",
            doc_number,
            len(result.contract_lines),
            len(result.authorizers),
            len(result.spr_urls),
        )
        return result

    @staticmethod
    def _general_document_number(soup: BeautifulSoup) -> str | None:
        """CONTRAT.AR contract pages: the number lives in a dedicated span
        (``lblValorNumeroDocumentoGeneral``) next to a bare "Contrato:" label."""
        span = soup.find("span", id=re.compile(r"lblValorNumeroDocumentoGeneral$", re.I))
        if span:
            val = clean_text(span.get_text())
            if val and re.search(r"-(?:OC|OCA|CON)\d{2}$", val, re.I):
                return val
        return None

    def _label_field(self, label_text: str, scope: Tag | None = None, index: int = 0) -> str | None:
        """Return the value next to the nth `<label>` matching `label_text`."""
        search_root = scope or self._soup
        pattern = re.compile(re.escape(label_text.lower().strip()), re.I)
        matches = []
        for lbl in search_root.find_all("label"):
            lbl_text = clean_text(lbl.get_text()) or ""
            if pattern.search(lbl_text.lower()):
                matches.append(lbl)

        if len(matches) > index:
            lbl = matches[index]
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
        return None

    def _span_field(self, label_text: str, scope: Tag | None = None) -> str | None:
        """Return the value next to a `<span>/<b>/<strong>/<td>` matching `label_text`."""
        search_root = scope or self._soup
        pattern = re.compile(re.escape(label_text.lower().strip()), re.I)
        for el in search_root.find_all(["span", "b", "strong", "td"]):
            el_text = clean_text(el.get_text()) or ""
            if pattern.search(el_text.lower()) and len(el_text) < 100:
                sib = el.find_next_sibling()
                if sib:
                    val = clean_text(sib.get_text())
                    if val:
                        return val
        return None

    def _field(self, label_text: str, scope: Tag | None = None) -> str | None:
        """Try a label lookup first, then a span-style lookup."""
        return self._label_field(label_text, scope) or self._span_field(label_text, scope)

    @staticmethod
    def _span_value(soup: BeautifulSoup, id_pattern: str) -> float | None:
        """Parse a numeric value from a span located by id regex."""
        span = soup.find("span", id=re.compile(id_pattern, re.I))
        if not span:
            return None
        raw = (clean_text(span.get_text()) or "").replace("%", "").strip()
        return parse_float(raw) if raw else None

    @staticmethod
    def _has_css_class(tag: Tag, class_name: str) -> bool:
        return class_name in (tag.get("class") or [])

    @classmethod
    def _panel_scope_from_heading(cls, heading: Tag) -> Tag | None:
        """Resolve the nearest Bootstrap panel container for a heading node."""
        panel_heading: Tag | None = None
        for parent in heading.parents:
            if isinstance(parent, Tag) and parent.name == "div" and cls._has_css_class(parent, "panel-heading"):
                panel_heading = parent
                break

        search_from = panel_heading if panel_heading is not None else heading
        for parent in search_from.parents:
            if isinstance(parent, Tag) and parent.name == "div" and cls._has_css_class(parent, "panel"):
                return parent
        return None

    def _parse_buyer_block(
        self, soup: BeautifulSoup,
    ) -> tuple[OrganizationModel | None, dict[str, str | None]]:
        """Extract the organization identity from the 'Datos Comprador' block."""

        def _field_in_scope(scope: Tag, label_text: str) -> str | None:
            pattern = re.compile(re.escape(label_text.lower()), re.I)
            for lbl in scope.find_all("label"):
                lt = clean_text(lbl.get_text()) or ""
                if pattern.search(lt.lower()):
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
            return None

        def _clean_optional(value: str | None) -> str | None:
            if not value:
                return None
            lowered = value.strip().lower()
            if lowered in {"no definido", "no informado", "s/d", "n/a", "-"}:
                return None
            return value

        scope: Tag = soup
        buyer_heading = soup.find(
            ["h1", "h2", "h3", "h4", "h5", "h6", "span", "div"],
            string=re.compile(r"Datos\s+(del\s+)?Comprador|Datos\s+Contratante", re.I),
        )
        if buyer_heading:
            panel = self._panel_scope_from_heading(buyer_heading)
            if panel:
                scope = panel

        saf_raw = _field_in_scope(scope, "Servicio Administrativo Financiero")
        if not saf_raw:
            return None, {}

        parts = saf_raw.split(" - ", 1)
        saf_code = parse_int(parts[0].strip()) if parts else None
        name = parts[1].strip() if len(parts) > 1 else saf_raw
        if saf_code is None:
            return None, {}

        contact = {
            "address": _clean_optional(_field_in_scope(scope, "Domicilio") or _field_in_scope(scope, "Dirección")),
            "postal_code": _clean_optional(_field_in_scope(scope, "Código postal") or _field_in_scope(scope, "Codigo postal")),
            "province": _clean_optional(_field_in_scope(scope, "Provincia")),
            "phone": _clean_optional(_field_in_scope(scope, "Teléfono") or _field_in_scope(scope, "Telefono")),
            "email": _clean_optional(_field_in_scope(scope, "Correo Electrónico") or _field_in_scope(scope, "Correo Electronico") or _field_in_scope(scope, "Email")),
        }

        return OrganizationModel(
            saf_code=saf_code,
            name=name,
            address=contact["address"],
            phone=contact["phone"],
            email=contact["email"],
        ), contact

    def _parse_provider_block(self, soup: BeautifulSoup) -> ProviderModel | None:
        """Extract the awarded provider identity from the 'Datos adjudicatario' block."""
        adj_heading = soup.find(
            ["h1", "h2", "h3", "h4", "h5", "h6", "span", "div"],
            string=re.compile(r"Datos\s+(del\s+)?adjudicatario|Datos\s+del\s+proveedor\s+adjudicado", re.I),
        )
        if not adj_heading:
            return None

        scope = self._panel_scope_from_heading(adj_heading)
        if not scope:
            scope = adj_heading.find_parent(["section", "fieldset", "table"])
        if not scope:
            scope = adj_heading.find_parent("div")
        if scope is None:
            return None

        def _lf(label_text: str) -> str | None:
            pattern = re.compile(re.escape(label_text.lower()), re.I)
            for lbl in scope.find_all("label"):
                lt = clean_text(lbl.get_text()) or ""
                if pattern.search(lt.lower()):
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
            return None

        cuit_raw = _lf("Número CUIT/CUIL/NIT") or _lf("CUIT/CUIL/NIT") or _lf("CUIT")
        if not cuit_raw:
            m = re.search(r"\b(\d{2}-\d{8}-\d)\b", scope.get_text())
            cuit_raw = m.group(1) if m else None

        cuit = clean_cuit(cuit_raw)
        if not cuit:
            return None

        return ProviderModel(
            cuit=cuit,
            business_name=_lf("Razón social") or _lf("Nombre"),
            sipro_entity_id=parse_int(_lf("Número ente") or _lf("Ente SIPRO")),
            address=_lf("Domicilio") or _lf("Dirección"),
            postal_code=_lf("Código postal"),
            city=_lf("Localidad") or _lf("Ciudad"),
            province=_lf("Provincia"),
            phone=_lf("Teléfono"),
            fax=_lf("Fax"),
            email=_lf("Email") or _lf("Correo electrónico"),
            sipro_status=_lf("Estado SIPRO") or _lf("Estado"),
        )

    def _parse_contract_lines(
        self, soup: BeautifulSoup, doc_number: str, is_oca: bool,
    ) -> list[ContractLineModel]:
        """Parse the awarded line items, merging the price and delivery tables.

        The site renders one table per line item, so every matching table is
        collected and merged by ``(renglón, alternativa)``.
        """
        lines: list[ContractLineModel] = []

        price_tables = self._find_all_tables_with_keywords(soup, ["precio unitario"])
        delivery_tables = self._find_all_tables_with_keywords(soup, ["dirección", "plazo"])
        price_table_set = {id(t) for t in price_tables}

        price_data: dict[tuple[int, int], dict] = {}
        for price_table in price_tables:
            rows = price_table.find_all("tr")
            if len(rows) < 2:
                continue
            headers = [clean_text(th.get_text(" ", strip=True)) or "" for th in rows[0].find_all(["th", "td"])]
            col = self._col_index_contract(headers)
            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue
                ct = [clean_text(c.get_text()) or "" for c in cells]

                def _cp(key: str, _ct=ct, _col=col) -> str | None:
                    idx = _col.get(key)
                    return _ct[idx] if idx is not None and idx < len(_ct) else None

                rn = parse_int(_cp("renglón") or _cp("renglon") or _cp("nro") or ct[0])
                alt = parse_int(_cp("alternativa") or (ct[1] if len(ct) > 1 else None)) or 1
                if rn is None:
                    continue
                price_data[(rn, alt)] = {
                    "catalog_code": _cp("código catálogo") or _cp("código"),
                    "description": _cp("descripción") or _cp("frente de obra"),
                    "awarded_quantity": parse_float(_cp("cantidad")),
                    "unit_of_measure": _cp("unidad medida") or _cp("unidad de medida") or _cp("u/m"),
                    "unit_price": parse_float(_cp("precio unitario")),
                    "total_price": self._parse_amount_cell(ct, col, "total"),
                    "currency": normalize_currency(_cp("moneda")),
                    "min_quantity": parse_float(_cp("cantidad mínima") or _cp("mínima")) if is_oca else None,
                    "max_quantity": parse_float(_cp("cantidad máxima") or _cp("máxima")) if is_oca else None,
                }

        delivery_data: dict[tuple[int, int], dict] = {}
        for delivery_table in delivery_tables:
            if id(delivery_table) in price_table_set:
                continue
            rows = delivery_table.find_all("tr")
            if len(rows) < 2:
                continue
            headers = [clean_text(th.get_text(" ", strip=True)) or "" for th in rows[0].find_all(["th", "td"])]
            col = self._col_index_contract(headers)
            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue
                ct = [clean_text(c.get_text()) or "" for c in cells]

                def _cd(key: str, _ct=ct, _col=col) -> str | None:
                    idx = _col.get(key)
                    return _ct[idx] if idx is not None and idx < len(_ct) else None

                rn = parse_int(_cd("renglón") or _cd("renglon") or _cd("nro") or ct[0])
                alt = parse_int(_cd("alternativa") or (ct[1] if len(ct) > 1 else None)) or 1
                if rn is None:
                    continue
                delivery_data[(rn, alt)] = {
                    "delivery_address": _cd("dirección"),
                    "delivery_term": _cd("plazo"),
                    "observations": _cd("observaciones"),
                    "catalog_code_fallback": _cd("código ítem") or _cd("código"),
                    "description_fallback": _cd("descripción"),
                }

        all_keys = set(price_data.keys()) | set(delivery_data.keys())
        for rn, alt in sorted(all_keys):
            pd = price_data.get((rn, alt), {})
            dd = delivery_data.get((rn, alt), {})
            lines.append(ContractLineModel(
                document_number=doc_number,
                line_number=rn,
                alternative_number=alt,
                catalog_code=pd.get("catalog_code") or dd.get("catalog_code_fallback"),
                description=pd.get("description") or dd.get("description_fallback"),
                awarded_quantity=pd.get("awarded_quantity"),
                unit_of_measure=pd.get("unit_of_measure"),
                unit_price=pd.get("unit_price"),
                total_price=pd.get("total_price"),
                currency=pd.get("currency"),
                delivery_address=dd.get("delivery_address"),
                delivery_term=dd.get("delivery_term"),
                observations=dd.get("observations"),
                min_quantity=pd.get("min_quantity"),
                max_quantity=pd.get("max_quantity"),
            ))

        return lines

    @staticmethod
    def _parse_document_observations(soup: BeautifulSoup) -> str | None:
        """Parse the free-text "Observaciones" rows under each detail block.

        CONTRAT.AR renders one ``rptDetalle_ctl<n>_observaciones`` div per
        detail section (below the renglones table). Long texts are truncated
        in the visible span and the full text moved to the ``title`` attribute
        of a ``lblVerMasObservaciones`` span. Line breaks are preserved.
        """
        blocks: list[str] = []
        for div in soup.find_all("div", id=re.compile(r"rptDetalle_ctl\d+_observaciones$", re.I)):
            more = div.find("span", id=re.compile(r"lblVerMasObservaciones$", re.I))
            raw = more.get("title") if more and more.get("title") else None
            if not raw:
                for span in div.find_all("span"):
                    text = span.get_text("\n")
                    if text and text.strip():
                        raw = text
                        break
            if not raw:
                continue
            lines = [clean_text(line) for line in raw.splitlines()]
            cleaned = "\n".join(line for line in lines if line)
            if cleaned and cleaned not in blocks:
                blocks.append(cleaned)
        return "\n".join(blocks) or None

    def _parse_authorizers(
        self, soup: BeautifulSoup, doc_number: str,
    ) -> tuple[list[AuthorizerModel], list[tuple[str, AuthorizedByRelProps]]]:
        """Parse the authorizer(s) block into authorizers and AUTHORIZED_BY rels."""
        authorizers: list[AuthorizerModel] = []
        rels: list[tuple[str, AuthorizedByRelProps]] = []

        table = self._find_table_with_keywords(soup, ["nombre autoridad", "cargo"])
        if table is None:
            table = self._find_table_with_keywords(soup, ["nombre autoridad", "tipo de autorizador"])
        if table is None:
            table = self._find_table_with_keywords(soup, ["autorizador", "nombre"])
        if table is None:
            return authorizers, rels

        rows = table.find_all("tr")
        if len(rows) < 2:
            return authorizers, rels

        headers = [clean_text(th.get_text()) or "" for th in rows[0].find_all(["th", "td"])]
        col = self._col_index_auth(headers)

        seen_names: set[str] = set()

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            cell_texts = [clean_text(c.get_text()) or "" for c in cells]

            def _c(key: str) -> str | None:
                idx = col.get(key)
                return cell_texts[idx] if idx is not None and idx < len(cell_texts) else None

            full_name = normalize_name(
                _c("nombre autoridad") or _c("nombre") or _c("autorizador") or _c("firmante")
            )
            if not full_name:
                continue

            if full_name not in seen_names:
                authorizers.append(AuthorizerModel(full_name=full_name))
                seen_names.add(full_name)

            raw_dt = _c("fecha autorización") or _c("fecha de autorización") or _c("fecha")
            parsed_dt = parse_datetime(raw_dt)
            if parsed_dt is None:
                parsed_d = parse_date(raw_dt)
                if parsed_d is not None:
                    parsed_dt = datetime.combine(parsed_d, datetime.min.time())

            rels.append((doc_number, AuthorizedByRelProps(
                authorizer_name=full_name,
                authorizer_type=_c("tipo de autorizador") or _c("tipo"),
                role=_c("cargo") or _c("rol"),
                authorized_at=parsed_dt,
            )))

        return authorizers, rels

    @staticmethod
    def _find_table_with_keywords(soup: BeautifulSoup, keywords: list[str]) -> Tag | None:
        """Find a table whose first row contains all keywords (case-insensitive)."""
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue
            # Space separator so consecutive TH tags don't fuse into 'preciounitario'.
            header_text = rows[0].get_text(separator=" ").lower()
            if all(kw.lower() in header_text for kw in keywords):
                return table
        return None

    @staticmethod
    def _find_all_tables_with_keywords(soup: BeautifulSoup, keywords: list[str]) -> list[Tag]:
        """Find all tables whose first row contains all keywords (case-insensitive)."""
        tables = []
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue
            header_text = rows[0].get_text(separator=" ").lower()
            if all(kw.lower() in header_text for kw in keywords):
                tables.append(table)
        return tables

    @staticmethod
    def _parse_amount_cell(cell_texts: list[str], col: dict, key: str) -> float | None:
        """Parse an amount from a cell, stripping a leading currency symbol."""
        idx = col.get(key)
        if idx is None or idx >= len(cell_texts):
            return None
        raw = re.sub(r"^[\s$€£%]+", "", cell_texts[idx])
        return parse_float(raw)

    @staticmethod
    def _parse_total_amount(soup: BeautifulSoup) -> float | None:
        """Parse the total amount from the summary spans at the bottom of the page."""
        import_total = soup.find("span", id=re.compile(r"lblImporteTotal$", re.I))
        if import_total:
            return parse_float(clean_text(import_total.get_text()))

        oca_total_lbl = soup.find(string=re.compile(r"Total de la Orden de Compra Abierta", re.I))
        if oca_total_lbl:
            sib = oca_total_lbl.find_next_sibling()
            if not sib and oca_total_lbl.parent:
                sib = oca_total_lbl.parent.find_next_sibling()
            if sib:
                v = re.sub(r"[^\d.,]", "", clean_text(sib.get_text()))
                return parse_float(v)

        importe_el = soup.find(string=re.compile(r"importe\s+total", re.I))
        if importe_el:
            parent = importe_el.find_parent()

            # React/Bootstrap column layout: label span in one col, value in the next.
            if parent and parent.name == "span" and parent.find_parent("h5"):
                col_div = parent.find_parent("div")
                if col_div:
                    val_div = col_div.find_next_sibling("div")
                    if val_div:
                        val_span = val_div.find("span")
                        if val_span:
                            return parse_float(clean_text(val_span.get_text()))

            sib = parent.find_next_sibling() if parent else None
            if sib:
                val = clean_text(sib.get_text())
                if val:
                    return parse_float(val)
            row = parent.find_parent("tr")
            if row:
                cells = row.find_all(["td", "th"])
                for i, cell in enumerate(cells):
                    if "importe total" in (clean_text(cell.get_text()) or "").lower():
                        if i + 1 < len(cells):
                            return parse_float(clean_text(cells[i + 1].get_text()))
        return None

    @staticmethod
    def _get_val_from_summary_table(soup: BeautifulSoup, title_regex: str, field_regex: str) -> str | None:
        """Read a value from a titled summary table (e.g. OCA extension tables)."""
        title_el = soup.find(string=re.compile(title_regex, re.I))
        if not title_el:
            return None
        table = title_el.find_parent().find_next("table")
        if not table:
            return None

        rows = table.find_all("tr")
        if len(rows) < 2:
            return None

        # Headers on row 0, values on row 1.
        headers = [clean_text(th.get_text()) or "" for th in rows[0].find_all(["th", "td"])]
        for i, h in enumerate(headers):
            if re.search(field_regex, h, re.I):
                cells = [clean_text(c.get_text()) or "" for c in rows[1].find_all(["th", "td"])]
                if i < len(cells):
                    return cells[i]
        return None

    @staticmethod
    def _extract_spr_urls(soup: BeautifulSoup) -> list[str]:
        """Extract SPR URLs from direct hrefs or postback option payloads."""
        urls: list[str] = []
        seen: set[str] = set()
        spr_re = re.compile(r"(/OC/VistaPreviaSolicitudProvisionCiudadano\.aspx\?qs=[^\"']+)", re.I)

        for a in soup.find_all("a", href=True):
            href = a.get("href", "") or ""
            candidate: str | None = None

            if "VistaPreviaSolicitudProvisionCiudadano.aspx" in href and not href.lower().startswith("javascript:"):
                candidate = href
            else:
                m = spr_re.search(href)
                if m:
                    candidate = m.group(1)

            if not candidate:
                continue

            abs_url = make_absolute(settings.base_url, candidate)
            if abs_url and abs_url not in seen:
                seen.add(abs_url)
                urls.append(abs_url)

        return urls

    @staticmethod
    def _col_index_contract(headers: list[str]) -> dict[str, int]:
        """Map contract-line column keywords to their header index."""
        keywords = [
            "renglón", "renglon", "nro", "alternativa",
            "código catálogo", "código ítem", "código",
            "descripción", "denominación", "frente de obra",
            "cantidad mínima", "mínima",
            "cantidad máxima", "máxima",
            "cantidad",
            "unidad medida", "unidad de medida", "u/m",
            "precio unitario",
            "moneda",
            "total",
            "dirección",
            "plazo",
            "observaciones",
        ]
        index: dict[str, int] = {}
        for i, header in enumerate(headers):
            lower = (header or "").lower().strip()
            for kw in keywords:
                if kw in lower and kw not in index:
                    index[kw] = i
        return index

    @staticmethod
    def _col_index_auth(headers: list[str]) -> dict[str, int]:
        """Map authorizer column keywords to their header index."""
        keywords = [
            "nombre autoridad", "nombre", "autorizador", "firmante",
            "tipo de autorizador", "tipo",
            "cargo", "rol",
            "fecha autorización", "fecha de autorización", "fecha",
        ]
        index: dict[str, int] = {}
        for i, header in enumerate(headers):
            lower = (header or "").lower().strip()
            for kw in keywords:
                if kw in lower and kw not in index:
                    index[kw] = i
        return index
