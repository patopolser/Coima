"""
offers_page.py - Comparative offer table parser for VerCuadroComparativo.aspx.

The page uses a Bootstrap accordion: each line item is a panel whose heading
holds the line-item info and whose collapse body lists one heading per bidder
followed by that bidder's detail table. A flat-table fallback handles older
portal versions.

Produces, per process: one Provider per bidder, one Bid per bidder, and one
BidLine per renglón x alternativa x bidder.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from scraper.models import BidLineModel, BidModel, ProviderModel
from utils.logging_config import get_logger
from utils.parsers import (
    clean_cuit,
    clean_text,
    normalize_currency,
    parse_bool,
    parse_float,
    parse_int,
)

logger = get_logger(__name__)

_ADJUDICATED_MARKERS = {"adjudicad", "ganador", "awarded", "success", "info"}


class OffersPageParser:
    """Parses the comparative offer table into providers, bids, and bid lines."""

    def __init__(self, html: str, process_number: str) -> None:
        self._soup = BeautifulSoup(html, "lxml")
        self._process_number = process_number
        self._providers: list[ProviderModel] = []
        self._bids: list[BidModel] = []
        self._bid_lines: list[BidLineModel] = []

    def parse(self) -> tuple[list[ProviderModel], list[BidModel], list[BidLineModel]]:
        """Parse the page and return ``(providers, bids, bid_lines)``."""
        # Primary layout: Bootstrap accordion (one panel-group per line item).
        panel_groups = self._soup.find_all("div", class_=lambda c: c and "panel-group" in c)
        if panel_groups:
            self._parse_panel_layout(panel_groups)

        # Fallback: flat table layout (older portal versions).
        if not self._bids:
            self._parse_table_layout()

        logger.info(
            "Process %s: %d bids, %d bid lines extracted.",
            self._process_number, len(self._bids), len(self._bid_lines),
        )
        return self._providers, self._bids, self._bid_lines

    def _parse_panel_layout(self, panel_groups: list[Tag]) -> None:
        """Parse the Bootstrap accordion layout."""
        seen_cuits: set[str] = set()
        bid_map: dict[str, BidModel] = {}

        for panel_group in panel_groups:
            panel_heading = panel_group.find(
                "div", class_=lambda c: c and "panel-heading" in c)
            line_number: int | None = None
            heading_catalog_code: str | None = None
            heading_description: str | None = None
            heading_requested_qty: float | None = None
            heading_uom: str | None = None

            line_table = panel_heading.find("table") if panel_heading else None
            if line_table:
                rows = line_table.find_all("tr")
                if len(rows) >= 2:
                    headers = [clean_text(th.get_text()) or "" for th in rows[0].find_all(["th", "td"])]
                    data = [clean_text(td.get_text()) or "" for td in rows[1].find_all(["td", "th"])]
                    col = self._col_map(headers)
                    line_number = parse_int(
                        self._get(data, col, "renglón")
                        or self._get(data, col, "renglon")
                        or (data[0] if data else None))
                    heading_catalog_code = self._get(data, col, "código del renglón") or self._get(data, col, "código")
                    heading_description = self._get(data, col, "descripción")
                    heading_uom = self._get(data, col, "um") or self._get(data, col, "unidad de medida")
                    heading_requested_qty = parse_float(
                        self._get(data, col, "cantidad solicitada") or self._get(data, col, "cantidad"))

            panel_collapse = panel_group.find(
                "div", class_=lambda c: c and "panel-collapse" in c)
            if not panel_collapse:
                continue

            list_group = panel_collapse.find("div", class_=lambda c: c and "list-group" in c)
            if not list_group:
                continue

            current_cuit: str | None = None

            for item in list_group.find_all("div", class_=lambda c: c and "list-group-item" in c):
                classes = " ".join(item.get("class", []))

                if "list-heading" in classes:
                    text = clean_text(item.get_text()) or ""
                    cuit, name = self._parse_bidder_header(text)
                    if not cuit:
                        continue
                    current_cuit = cuit

                    if cuit not in seen_cuits:
                        seen_cuits.add(cuit)
                        self._providers.append(ProviderModel(cuit=cuit, business_name=name))
                        bid = BidModel(
                            process_number=self._process_number,
                            provider_cuit=cuit,
                            status=self._extract_status(item),
                            total_amount=None,
                            currency=None,
                        )
                        self._bids.append(bid)
                        bid_map[cuit] = bid

                elif current_cuit and "list-heading" not in classes:
                    table = item.find("table")
                    if not table:
                        continue
                    rows = table.find_all("tr")
                    if len(rows) < 2:
                        continue

                    headers = [clean_text(th.get_text()) or "" for th in rows[0].find_all(["th", "td"])]
                    col = self._col_map(headers)

                    for row in rows[1:]:
                        cells = row.find_all(["td", "th"])
                        if not cells:
                            continue
                        ct = [clean_text(c.get_text()) or "" for c in cells]

                        alt = parse_int(self._get(ct, col, "alternativa")) or 1
                        unit_price = parse_float(self._get(ct, col, "precio unitario"))
                        total_per_line = parse_float(
                            self._get(ct, col, "total por renglón")
                            or self._get(ct, col, "total renglón")
                            or self._get(ct, col, "total")
                        )
                        offered_qty = parse_float(
                            self._get(ct, col, "cantidad ofertada")
                            or self._get(ct, col, "cant. ofertada")
                            or self._get(ct, col, "cantidad")
                        )
                        line_currency = normalize_currency(self._get(ct, col, "moneda"))
                        is_adj = self._is_adjudicated(row, bid_map.get(current_cuit))

                        if line_number is None:
                            continue

                        self._bid_lines.append(BidLineModel(
                            process_number=self._process_number,
                            provider_cuit=current_cuit,
                            line_number=line_number,
                            alternative_number=alt,
                            catalog_code=heading_catalog_code,
                            description=heading_description,
                            requested_quantity=heading_requested_qty,
                            unit_of_measure=heading_uom,
                            offered_quantity=offered_qty,
                            unit_price=unit_price,
                            total_per_line=total_per_line,
                            currency=line_currency,
                            technical_specifications=self._get(ct, col, "especificaciones técnicas") or self._get(ct, col, "especificaciones"),
                            is_national_good=parse_bool(self._get(ct, col, "bien nacional")),
                            is_adjudicated=is_adj,
                        ))

                        if current_cuit in bid_map and total_per_line is not None:
                            b = bid_map[current_cuit]
                            b.total_amount = (b.total_amount or 0) + total_per_line
                            if not b.currency and line_currency:
                                b.currency = line_currency

    def _parse_table_layout(self) -> None:
        """Fallback parser for flat per-provider tables."""
        for table in self._soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue

            header_texts = [clean_text(th.get_text()) or "" for th in rows[0].find_all(["th", "td"])]
            joined = " ".join(header_texts).lower()
            if not any(kw in joined for kw in ("precio unitario", "oferta", "oferente", "alternativa")):
                continue

            col = self._col_map(header_texts)
            current_cuit: str | None = None

            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue

                row_text = clean_text(row.get_text()) or ""
                ct = [clean_text(c.get_text()) or "" for c in cells]

                # Detect header row by CUIT presence.
                cuit_match = re.search(r"\b(\d{2}-\d{8}-\d)\b", row_text)
                if cuit_match and len(cells) <= 5:
                    current_cuit = clean_cuit(cuit_match.group(1))
                    if current_cuit and not any(p.cuit == current_cuit for p in self._providers):
                        name = self._extract_name_from_row(row_text, cuit_match.group(1))
                        self._providers.append(ProviderModel(cuit=current_cuit, business_name=name))
                        self._bids.append(BidModel(
                            process_number=self._process_number,
                            provider_cuit=current_cuit,
                            status=self._extract_status(row),
                        ))
                    continue

                if current_cuit is None:
                    continue

                line_number = parse_int(
                    self._get(ct, col, "renglón") or self._get(ct, col, "nro") or ct[0])
                if line_number is None:
                    continue

                self._bid_lines.append(BidLineModel(
                    process_number=self._process_number,
                    provider_cuit=current_cuit,
                    line_number=line_number,
                    alternative_number=parse_int(self._get(ct, col, "alternativa")) or 1,
                    catalog_code=self._get(ct, col, "código"),
                    description=self._get(ct, col, "descripción"),
                    requested_quantity=parse_float(self._get(ct, col, "cantidad solicitada")),
                    offered_quantity=parse_float(
                        self._get(ct, col, "cantidad ofertada") or self._get(ct, col, "cantidad")),
                    unit_of_measure=self._get(ct, col, "unidad de medida"),
                    unit_price=parse_float(self._get(ct, col, "precio unitario")),
                    total_per_line=parse_float(
                        self._get(ct, col, "total por renglón") or self._get(ct, col, "total")),
                    currency=normalize_currency(self._get(ct, col, "moneda")),
                    technical_specifications=self._get(ct, col, "especificaciones técnicas"),
                    is_national_good=parse_bool(self._get(ct, col, "bien nacional")),
                    is_adjudicated=self._is_adjudicated(row, None),
                ))

    @staticmethod
    def _parse_bidder_header(text: str) -> tuple[str | None, str | None]:
        """Parse a header like "COMPANY NAME  -  30716270366" into (cuit, name)."""
        # CUIT without dashes: 11 digits.
        m = re.search(r"(?:^|\s)-\s+(\d{11})\s*$", text.strip())
        if m:
            cuit_raw = m.group(1)
            formatted = f"{cuit_raw[:2]}-{cuit_raw[2:10]}-{cuit_raw[10]}"
            cuit = clean_cuit(formatted)
            name_part = text[:m.start()].strip(" -").strip()
            return cuit, clean_text(name_part)

        # CUIT with dashes.
        m2 = re.search(r"\b(\d{2}-\d{8}-\d)\b", text)
        if m2:
            cuit = clean_cuit(m2.group(1))
            name_part = text[:m2.start()].strip(" --").strip()
            return cuit, clean_text(name_part)

        return None, None

    @staticmethod
    def _col_map(headers: list[str]) -> dict[str, int]:
        """Map known column keywords to their index in a header row."""
        keywords = [
            "renglón", "renglon", "nro",
            "código del renglón", "código", "descripción",
            "cantidad solicitada", "cantidad",
            "um", "unidad de medida",
            "alternativa",
            "precio unitario",
            "cantidad ofertada", "cant. ofertada",
            "total por renglón", "total renglón", "total",
            "moneda",
            "especificaciones técnicas", "especificaciones",
            "bien nacional",
        ]
        index: dict[str, int] = {}
        for i, header in enumerate(headers):
            lower = (header or "").lower().strip()
            for kw in keywords:
                if kw in lower and kw not in index:
                    index[kw] = i
        return index

    @staticmethod
    def _get(cell_texts: list[str], col: dict, key: str) -> str | None:
        """Return the cell text for a mapped column key, or None."""
        idx = col.get(key)
        return cell_texts[idx] if idx is not None and idx < len(cell_texts) else None

    @staticmethod
    def _extract_status(element: Tag) -> str | None:
        """Extract a bid status from CSS classes or text."""
        classes = " ".join(element.get("class", [])).lower() if element else ""
        text = (element.get_text() or "").lower() if element else ""
        if "success" in classes or "adjudicad" in text:
            return "Adjudicada"
        if "warning" in classes or "no admitida" in text:
            return "No admitida"
        if "admitida" in text:
            return "Admitida"
        return None

    @staticmethod
    def _extract_name_from_row(text: str, cuit_str: str) -> str | None:
        """Extract the business name preceding a CUIT in a flat-table row."""
        idx = text.find(cuit_str)
        if idx > 0:
            return clean_text(text[:idx].strip(" -"))
        return None

    @staticmethod
    def _is_adjudicated(row: Tag, bid: BidModel | None) -> bool:
        """Return True if a bid-line row is marked adjudicated (awarded)."""
        row_class = " ".join(row.get("class", [])).lower()
        row_text = (row.get_text() or "").lower()
        return any(m in row_class or m in row_text for m in _ADJUDICATED_MARKERS)
