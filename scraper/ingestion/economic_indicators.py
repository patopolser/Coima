"""
economic_indicators.py - Economic-indicator graph support.

Creates economic indicator nodes (inflation indexes, FX rates) and the
relationships that contextualise procurement amounts, without mutating the
scraped amount fields themselves.

Responsibilities are split into three classes:

  * EconomicIndicatorsClient:   fetch observations from the INDEC and BCRA
                                public APIs.
  * IndicatorQueryBuilder:      bulk-upsert indicator nodes.
  * EconomicRelationshipBuilder: link price-bearing nodes to the matching
                                indicators and store `ars_historico` on the
                                relationship.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Iterable

import requests
from requests.exceptions import SSLError
from urllib3.exceptions import InsecureRequestWarning

from ingestion.price_entities import PRICE_ENTITIES_BY_KIND, PriceEntitySpec
from scraper.models import ExchangeRateModel, InflationIndexModel, ProcessResult
from utils.logging_config import get_logger
from utils.parsers import normalize_currency

logger = get_logger(__name__)

INDEC_IPC_SERIES_ID = "INDEC_IPC_NIVEL_GENERAL_NACIONAL"
INDEC_IPC_FIELD_ID = "148.3_INIVELNAL_DICI_M_26"
BCRA_IPC_SERIES_ID = "BCRA_IPC_RECONSTRUCTED_MOM"
BCRA_IPC_MONTHLY_VARIATION_ID = 27
FX_RATE_TYPE = "BCRA_ESTADISTICAS_CAMBIARIAS"

INDEC_SERIES_URL = "https://apis.datos.gob.ar/series/api/series/"
BCRA_MONETARY_URL = "https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias"
BCRA_FX_URL = "https://api.bcra.gob.ar/estadisticascambiarias/v1.0/Cotizaciones"

_INDEC_START = date(2016, 12, 1)


def _period(value: date) -> str:
    """Return the ``YYYY-MM`` period string for a date."""
    return f"{value.year:04d}-{value.month:02d}"


def _period_end(value: date) -> date:
    """Return the last calendar day of the month containing ``value``."""
    return date(value.year, value.month, calendar.monthrange(value.year, value.month)[1])


def _add_months(value: date, months: int) -> date:
    """Return the first day of the month ``months`` away from ``value``."""
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    return date(year, month, 1)


def _coerce_date(value: object) -> date | None:
    """Coerce a date/datetime to a plain date, or None otherwise."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _inflation_series_id(observed_on: date) -> str:
    """Pick the inflation series id appropriate for an observation date."""
    return BCRA_IPC_SERIES_ID if observed_on < _INDEC_START else INDEC_IPC_SERIES_ID


class EconomicIndicatorsClient:
    """Fetches inflation and FX observations from the INDEC and BCRA APIs."""

    def __init__(self) -> None:
        self._tls_verify = True

    def fetch(
        self,
        start_date: date,
        currencies: Iterable[str],
    ) -> tuple[list[InflationIndexModel], list[ExchangeRateModel]]:
        """Fetch all configured economic indicator observations.

        Args:
            start_date: Earliest observation date to request.
            currencies: Currencies to fetch FX rates for (ARS is ignored).

        Returns:
            A ``(inflation_indexes, exchange_rates)`` tuple. Inflation indexes
            are ordered with the BCRA fallback series first, then INDEC.
        """
        today = date.today()
        currencies = sorted({c.upper() for c in currencies if c and c.upper() != "ARS"})

        indec_indexes = self._fetch_indec_ipc_indexes(max(start_date, _INDEC_START), today)
        fallback_indexes = self._fetch_bcra_fallback_indexes(
            start_date, min(today, date(2016, 11, 30))
        )
        fx_rates = [
            rate
            for currency in currencies
            for rate in self._fetch_exchange_rates(currency, start_date, today)
        ]

        logger.info(
            "Fetched economic indicators: %d inflation indexes, %d FX rates.",
            len(indec_indexes) + len(fallback_indexes),
            len(fx_rates),
        )
        return fallback_indexes + indec_indexes, fx_rates

    def _fetch_indec_ipc_indexes(
        self, start_date: date, end_date: date,
    ) -> list[InflationIndexModel]:
        """Fetch monthly INDEC IPC index levels in the date range."""
        if start_date > end_date:
            return []

        payload = self._request_json(
            INDEC_SERIES_URL,
            {
                "ids": INDEC_IPC_FIELD_ID,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "limit": 5000,
            },
        )
        fetched_at = datetime.utcnow()
        indexes: list[InflationIndexModel] = []
        for row in payload.get("data") or []:
            if len(row) < 2 or row[1] is None:
                continue
            period_start = date.fromisoformat(row[0])
            indexes.append(
                InflationIndexModel(
                    series_id=INDEC_IPC_SERIES_ID,
                    period=_period(period_start),
                    period_start=period_start,
                    period_end=_period_end(period_start),
                    index_value=float(row[1]),
                    base="dic-2016=100",
                    source="INDEC IPC Nivel General Nacional",
                    source_url=f"{INDEC_SERIES_URL}?ids={INDEC_IPC_FIELD_ID}",
                    fetched_at=fetched_at,
                )
            )
        return indexes

    def _fetch_bcra_fallback_indexes(
        self, start_date: date, end_date: date,
    ) -> list[InflationIndexModel]:
        """Reconstruct pre-INDEC monthly index levels from BCRA variation data.

        Fetches monthly inflation variations through Dec-2016 so pre-INDEC
        months can be chained backwards and anchored to the INDEC Dec-2016 base
        of 100.
        """
        if start_date > end_date:
            return []

        payload = self._request_json(
            f"{BCRA_MONETARY_URL}/{BCRA_IPC_MONTHLY_VARIATION_ID}",
            {
                "Desde": start_date.isoformat(),
                "Hasta": _period_end(_INDEC_START).isoformat(),
                "limit": 2000,
            },
        )
        variations: dict[date, float] = {}
        for result in payload.get("results") or []:
            for item in result.get("detalle") or []:
                if item.get("fecha") and item.get("valor") is not None:
                    obs_date = date.fromisoformat(item["fecha"])
                    variations[date(obs_date.year, obs_date.month, 1)] = float(item["valor"])

        if not variations:
            return []

        current_month = date(2016, 11, 1)
        values: dict[date, float] = {}
        next_level = 100.0
        while current_month >= date(start_date.year, start_date.month, 1):
            next_month = _add_months(current_month, 1)
            next_variation = variations.get(next_month)
            if next_variation is None:
                break
            level = next_level / (1 + (next_variation / 100.0))
            values[current_month] = level
            next_level = level
            current_month = _add_months(current_month, -1)

        fetched_at = datetime.utcnow()
        return [
            InflationIndexModel(
                series_id=BCRA_IPC_SERIES_ID,
                period=_period(period_start),
                period_start=period_start,
                period_end=_period_end(period_start),
                index_value=value,
                base="anchored to INDEC dic-2016=100",
                source="BCRA Principales Variables variable 27",
                source_url=f"{BCRA_MONETARY_URL}/{BCRA_IPC_MONTHLY_VARIATION_ID}",
                fetched_at=fetched_at,
            )
            for period_start, value in sorted(values.items())
            if start_date <= period_start <= end_date
        ]

    def _fetch_exchange_rates(
        self, currency: str, start_date: date, end_date: date,
    ) -> list[ExchangeRateModel]:
        """Fetch daily BCRA official exchange rates for a currency."""
        rows: list[ExchangeRateModel] = []
        offset = 0
        limit = 1000
        fetched_at = datetime.utcnow()

        while True:
            payload = self._request_json(
                f"{BCRA_FX_URL}/{currency}",
                {
                    "fechaDesde": start_date.isoformat(),
                    "fechaHasta": end_date.isoformat(),
                    "limit": limit,
                    "offset": offset,
                },
            )
            result_rows = payload.get("results") or []
            for row in result_rows:
                detail = (row.get("detalle") or [{}])[0]
                if row.get("fecha") and detail.get("tipoCotizacion") is not None:
                    rows.append(
                        ExchangeRateModel(
                            currency=currency,
                            observed_date=date.fromisoformat(row["fecha"]),
                            rate_type=FX_RATE_TYPE,
                            ars_per_unit=float(detail["tipoCotizacion"]),
                            source="BCRA Estadisticas Cambiarias",
                            source_url=f"{BCRA_FX_URL}/{currency}",
                            fetched_at=fetched_at,
                        )
                    )

            resultset = (payload.get("metadata") or {}).get("resultset") or {}
            count = int(resultset.get("count") or len(result_rows))
            offset += len(result_rows)
            if not result_rows or offset >= count:
                break

        return rows

    def _request_json(self, url: str, params: dict[str, Any]) -> dict:
        """GET a JSON payload, retrying once without TLS verification on SSLError."""
        try:
            response = requests.get(url, params=params, timeout=30, verify=self._tls_verify)
        except SSLError:
            logger.warning(
                "TLS verification failed for economic API; retrying this run without verification."
            )
            self._tls_verify = False
            requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)
            response = requests.get(url, params=params, timeout=30, verify=False)
        response.raise_for_status()
        return response.json()


class IndicatorQueryBuilder:
    """Builders that bulk-upsert economic indicator nodes."""

    @staticmethod
    def batch_merge_inflation_indexes(
        indexes: list[InflationIndexModel],
    ) -> tuple[str, dict]:
        """Bulk-upsert InflationIndex nodes keyed by (series_id, period)."""
        query = """
        UNWIND $batch AS row
        MERGE (idx:InflationIndex {series_id: row.series_id, period: row.period})
        SET idx += row.props
        """
        return query, {"batch": [
            {
                "series_id": idx.series_id,
                "period": idx.period,
                "props": IndicatorQueryBuilder._props(idx, {"series_id", "period"}),
            }
            for idx in indexes
        ]}

    @staticmethod
    def batch_merge_exchange_rates(rates: list[ExchangeRateModel]) -> tuple[str, dict]:
        """Bulk-upsert ExchangeRate nodes keyed by (currency, observed_date, rate_type)."""
        query = """
        UNWIND $batch AS row
        MERGE (fx:ExchangeRate {
            currency: row.currency,
            observed_date: row.observed_date,
            rate_type: row.rate_type
        })
        SET fx += row.props
        """
        return query, {"batch": [
            {
                "currency": rate.currency,
                "observed_date": rate.observed_date,
                "rate_type": rate.rate_type,
                "props": IndicatorQueryBuilder._props(
                    rate, {"currency", "observed_date", "rate_type"}),
            }
            for rate in rates
        ]}

    @staticmethod
    def _props(model: Any, exclude_keys: set[str]) -> dict[str, Any]:
        """Dump a model to a dict, dropping the given keys and None values."""
        return {
            key: value
            for key, value in model.model_dump().items()
            if key not in exclude_keys and value is not None
        }


class EconomicRelationshipBuilder:
    """Builds VALUED_AT_INFLATION / VALUED_AT_FX relationships for one process.

    ``ars_historico`` is stored on the relationship (not the node): the local
    ARS amount for inflation links, and ``amount * ars_per_unit`` for FX links.
    """

    def build_batches(self, result: ProcessResult) -> list[tuple[str, dict]]:
        """Return the relationship-creation queries for a scraped process."""
        inflation: dict[str, list[dict]] = defaultdict(list)
        fx: dict[str, list[dict]] = defaultdict(list)

        process_date = _coerce_date(
            result.process.opening_date
            or result.process.scheduled_portal_publish_date
            or result.process.official_gazette_publish_date
            or result.process.scraped_at
        )
        fallback_currency = self._first_process_currency(result)

        bid_by_provider = {bid.provider_cuit: bid for bid in result.bids}
        doc_by_number = {doc.document_number: doc for doc in result.contractual_documents}
        spr_by_number = {spr.request_number: spr for spr in result.provision_requests}

        for bid in result.bids:
            observed_on = _coerce_date(bid.submitted_at) or process_date
            fields = self._amount_fields(
                [(bid.total_amount, bid.currency or fallback_currency, "total_amount")])
            self._append_rows("bid", self._bid_key(bid), observed_on, fields, inflation, fx)

        for line in result.bid_lines:
            bid = bid_by_provider.get(line.provider_cuit)
            observed_on = _coerce_date(bid.submitted_at if bid else None) or process_date
            currency = line.currency or (bid.currency if bid else None) or fallback_currency
            fields = self._amount_fields([
                (line.unit_price, currency, "unit_price"),
                (line.total_per_line, currency, "total_per_line"),
            ])
            self._append_rows("bid_line", self._bid_line_key(line), observed_on, fields, inflation, fx)

        for doc in result.contractual_documents:
            observed_on = _coerce_date(doc.perfection_date) or process_date
            fields = self._amount_fields([
                (doc.total_amount, doc.currency or fallback_currency, "total_amount"),
                (doc.max_extendable_amount, doc.extension_currency or doc.currency or fallback_currency, "max_extendable_amount"),
                (doc.available_extension_amount, doc.extension_currency or doc.currency or fallback_currency, "available_extension_amount"),
            ])
            self._append_rows(
                "contractual_document",
                {"document_number": doc.document_number, "source": doc.source or "comprar"},
                observed_on, fields, inflation, fx)

        for line in result.contract_lines:
            doc = doc_by_number.get(line.document_number)
            observed_on = _coerce_date(doc.perfection_date if doc else None) or process_date
            currency = line.currency or (doc.currency if doc else None) or fallback_currency
            fields = self._amount_fields([
                (line.unit_price, currency, "unit_price"),
                (line.total_price, currency, "total_price"),
            ])
            self._append_rows(
                "contract_line", self._contract_line_key(line), observed_on, fields, inflation, fx)

        for spr in result.provision_requests:
            observed_on = _coerce_date(spr.created_at) or process_date
            fields = self._amount_fields(
                [(spr.total_amount, spr.currency or fallback_currency, "total_amount")])
            self._append_rows(
                "provision_request", {"request_number": spr.request_number},
                observed_on, fields, inflation, fx)

        for line in result.provision_request_lines:
            spr = spr_by_number.get(line.request_number)
            observed_on = _coerce_date(spr.created_at if spr else None) or process_date
            currency = line.currency or (spr.currency if spr else None) or fallback_currency
            fields = self._amount_fields([
                (line.unit_price, currency, "unit_price"),
                (line.total_price, currency, "total_price"),
            ])
            self._append_rows(
                "provision_request_line", self._provision_line_key(line),
                observed_on, fields, inflation, fx)

        queries: list[tuple[str, dict]] = []
        for kind, rows in inflation.items():
            queries.append(self._inflation_query(PRICE_ENTITIES_BY_KIND[kind], rows))
        for kind, rows in fx.items():
            queries.append(self._fx_query(PRICE_ENTITIES_BY_KIND[kind], rows))
        return queries

    def _append_rows(
        self,
        kind: str,
        key: dict,
        observed_on: date | None,
        fields_by_currency: dict[str, list[str]],
        inflation: dict[str, list[dict]],
        fx: dict[str, list[dict]],
    ) -> None:
        """Accumulate inflation and FX batch rows for one priced node."""
        if not observed_on or not fields_by_currency:
            return

        all_fields = sorted({field for fields in fields_by_currency.values() for field in fields})
        inflation[kind].append({
            **key,
            "series_id": _inflation_series_id(observed_on),
            "period": _period(observed_on),
            "economic_date": observed_on,
            "amount_fields": all_fields,
            "matching_strategy": "same_month",
        })

        for currency, amount_fields in fields_by_currency.items():
            if currency == "ARS":
                continue
            fx[kind].append({
                **key,
                "currency": currency,
                "rate_type": FX_RATE_TYPE,
                "economic_date": observed_on,
                "amount_fields": sorted(amount_fields),
            })

    @staticmethod
    def _inflation_query(spec: PriceEntitySpec, rows: list[dict]) -> tuple[str, dict]:
        """Build the VALUED_AT_INFLATION query, storing ars_historico for ARS amounts."""
        ars_set = ""
        if spec.total_field:
            ars_set += (
                f",\n        r.ars_historico = CASE"
                f" WHEN coalesce(n.currency, 'ARS') = 'ARS' AND n.{spec.total_field} IS NOT NULL"
                f" THEN n.{spec.total_field} ELSE null END"
            )
        if spec.unit_field:
            ars_set += (
                f",\n        r.ars_historico_unit_price = CASE"
                f" WHEN coalesce(n.currency, 'ARS') = 'ARS' AND n.{spec.unit_field} IS NOT NULL"
                f" THEN n.{spec.unit_field} ELSE null END"
            )

        # Resolve the InflationIndex by exact period, or the closest earlier one
        # when the period's IPC has not been published yet (INDEC lags ~6 weeks,
        # so current/prior-month amounts have no same-month node at ingestion).
        query = f"""
        UNWIND $batch AS row
        {spec.node_match("n", "row")}
        CALL (row) {{
            MATCH (idx:InflationIndex {{series_id: row.series_id}})
            WHERE idx.period <= row.period
            RETURN idx ORDER BY idx.period DESC LIMIT 1
        }}
        MERGE (n)-[r:VALUED_AT_INFLATION]->(idx)
        SET r.economic_date = row.economic_date,
            r.amount_fields = row.amount_fields,
            r.matching_strategy = CASE WHEN idx.period = row.period THEN 'same_month' ELSE 'nearest_prior' END,
            r.series_id = row.series_id{ars_set}
        """
        return query, {"batch": rows}

    @staticmethod
    def _fx_query(spec: PriceEntitySpec, rows: list[dict]) -> tuple[str, dict]:
        """Build the VALUED_AT_FX query, storing ars_historico at the historical rate.

        Uses the variable-scope ``CALL (row)`` syntax required by Neo4j 5.
        """
        ars_set = ""
        if spec.total_field:
            ars_set += (
                f",\n        r.ars_historico = CASE"
                f" WHEN n.{spec.total_field} IS NOT NULL"
                f" THEN round(n.{spec.total_field} * fx.ars_per_unit, 2) ELSE null END"
            )
        if spec.unit_field:
            ars_set += (
                f",\n        r.ars_historico_unit_price = CASE"
                f" WHEN n.{spec.unit_field} IS NOT NULL"
                f" THEN round(n.{spec.unit_field} * fx.ars_per_unit, 2) ELSE null END"
            )

        query = f"""
        UNWIND $batch AS row
        {spec.node_match("n", "row")}
        CALL (row) {{
            MATCH (fx:ExchangeRate {{currency: row.currency, rate_type: row.rate_type}})
            WHERE fx.observed_date <= row.economic_date
            RETURN fx
            ORDER BY fx.observed_date DESC
            LIMIT 1
        }}
        MERGE (n)-[r:VALUED_AT_FX]->(fx)
        SET r.economic_date = row.economic_date,
            r.currency = row.currency,
            r.amount_fields = row.amount_fields,
            r.matching_strategy = CASE
                WHEN fx.observed_date = row.economic_date THEN 'exact_day'
                ELSE 'previous_business_day'
            END{ars_set}
        """
        return query, {"batch": rows}

    @staticmethod
    def _amount_fields(
        specs: list[tuple[float | None, str | None, str]],
    ) -> dict[str, list[str]]:
        """Group amount field names by normalised currency, skipping null amounts."""
        fields_by_currency: dict[str, list[str]] = defaultdict(list)
        for amount, currency, field_name in specs:
            normalized_currency = normalize_currency(currency) if currency else None
            if amount is not None and normalized_currency:
                fields_by_currency[normalized_currency].append(field_name)
        return dict(fields_by_currency)

    @staticmethod
    def _first_process_currency(result: ProcessResult) -> str | None:
        """Return the first normalisable currency declared on the process."""
        for currency in result.process.currencies:
            normalized = normalize_currency(currency)
            if normalized:
                return normalized
        return None

    @staticmethod
    def _bid_key(bid: Any) -> dict:
        return {"process_number": bid.process_number, "provider_cuit": bid.provider_cuit}

    @staticmethod
    def _bid_line_key(line: Any) -> dict:
        return {
            "process_number": line.process_number,
            "provider_cuit": line.provider_cuit,
            "line_number": line.line_number,
            "alternative_number": line.alternative_number,
        }

    @staticmethod
    def _contract_line_key(line: Any) -> dict:
        return {
            "document_number": line.document_number,
            "source": line.source or "comprar",
            "line_number": line.line_number,
            "alternative_number": line.alternative_number or 1,
        }

    @staticmethod
    def _provision_line_key(line: Any) -> dict:
        return {
            "request_number": line.request_number,
            "line_number": line.line_number,
            "alternative_number": line.alternative_number or 1,
        }
