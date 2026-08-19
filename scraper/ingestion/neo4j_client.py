"""
neo4j_client.py - Neo4j driver wrapper for the scraper ingestion layer.

Owns the connection, applies schema constraints and indexes once per database,
and bulk-ingests `ProcessResult` objects in UNWIND batches that drop the
per-process round-trip count from ~120 to ~18. All MERGE-based so re-running
the scraper is idempotent, and transient errors are retried with exponential
backoff.
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any, Optional

from neo4j import GraphDatabase, Session
from neo4j.exceptions import ServiceUnavailable, TransientError

from config import settings
from ingestion.economic_indicators import (
    EconomicIndicatorsClient,
    EconomicRelationshipBuilder,
    IndicatorQueryBuilder,
)
from ingestion.cypher_queries import (
    LEGACY_UNIQUE_CONSTRAINTS,
    SCHEMA_QUERIES,
    BatchQueryBuilder,
    NodeQueryBuilder,
)
from scraper.models import ProcessResult
from utils.logging_config import get_logger
from utils.parsers import clean_text

logger = get_logger(__name__)

_TRANSIENT_RETRIES = 3

# Schema version. Bump this when SCHEMA_QUERIES changes so the once-per-database
# guard re-applies the setup on the next run.
# v2: multi-portal support (CONTRAT.AR). Backfills source='comprar' on legacy
# nodes and replaces the ContractingUnit/ProcurementRequest/ContractualDocument
# single-key constraints with (key, source) composites.
# v3: Dictamen node ((process_number, source, sequence) unique) plus its
# PRE_ADJUDICATES / REJECTED edges; EVALUATED_BY now originates from Dictamen.
# v4: dictamen signers are their own DictamenSigner nodes (keyed by username),
# no longer Authorizer nodes; EVALUATED_BY now targets DictamenSigner.
_SCHEMA_VERSION = 4

# Labels whose nodes get source='comprar' backfilled by the v2 migration:
# the first three (plus ContractLine) now carry source in their MERGE keys;
# Process carries it for the cross-source ingestion guard and filtering.
_V2_BACKFILL_LABELS = (
    "Process",
    "ContractingUnit",
    "ProcurementRequest",
    "ContractualDocument",
    "ContractLine",
)

def _normalize_status(value: str) -> str:
    """Lowercase, strip accents, and collapse whitespace for status matching."""
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(without_accents.lower().split())


def _months_ago(months: int) -> datetime:
    """Return midnight of the day `months` calendar months before today."""
    now = datetime.now()
    total = (now.year * 12 + (now.month - 1)) - months
    year, month_index = divmod(total, 12)
    month = month_index + 1
    day = min(now.day, calendar.monthrange(year, month)[1])
    return datetime(year, month, day)


def _normalize_address(value: str) -> Optional[tuple[str, str]]:
    cleaned = clean_text(value)
    if not cleaned:
        return None
    return cleaned, cleaned.lower()


def _normalize_email(value: str) -> Optional[tuple[str, str]]:
    cleaned = clean_text(value)
    if not cleaned:
        return None
    return cleaned, cleaned.lower()


def _normalize_phone(value: str) -> Optional[tuple[str, str]]:
    cleaned = clean_text(value)
    if not cleaned:
        return None
    digits = re.sub(r"\D", "", cleaned)
    key = digits or cleaned.lower()
    return cleaned, key


class Neo4jClient:
    """Manages a Neo4j connection plus schema setup and batch ingestion.

    Usage:
        with Neo4jClient() as client:
            client.setup_schema()
            client.ingest_batch(results)
    """

    def __init__(self) -> None:
        self._driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
            max_connection_pool_size=settings.neo4j_max_conn,
        )

    def __enter__(self) -> "Neo4jClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def close(self) -> None:
        self._driver.close()

    def get_open_process_numbers(self, months: int, source: str = "comprar") -> list[str]:
        """Return process numbers of non-terminal processes from the last `months`.

        "Recent" is measured by ``opening_date``, falling back to
        ``scheduled_portal_publish_date`` when the opening date is absent. Only
        processes of the given `source` portal are returned, since each run
        scrapes a single portal.
        """
        cutoff = _months_ago(months)
        query = """
        MATCH (p:Process)
        WHERE coalesce(p.opening_date, p.scheduled_portal_publish_date) >= $cutoff
          AND coalesce(p.source, 'comprar') = $source
        RETURN p.process_number AS pn, p.status AS status
        """
        open_numbers: list[str] = []
        with self._driver.session() as session:
            for record in session.run(query, {"cutoff": cutoff, "source": source or "comprar"}):
                pn = record["pn"]
                if not pn:
                    continue
                status = record["status"]

                open_numbers.append(pn)
        logger.info(
            "Found %d open (non-terminal) processes since %s.",
            len(open_numbers), cutoff.date().isoformat(),
        )
        return open_numbers

    def setup_schema(self, force: bool = False) -> None:
        """Apply schema constraints and indexes once per database, then refresh indicators.

        A `(:_SchemaMeta {key: 'schema'})` marker node records the applied
        schema version; constraints and indexes are only re-applied when the
        marker is absent or outdated. Economic indicators (InflationIndex and
        ExchangeRate nodes) are refreshed on every call because they are
        time-series data that grow monthly and their MERGE queries are
        idempotent.

        Args:
            force: Re-apply constraints/indexes even if already at current version.
        """
        with self._driver.session() as session:
            if force or not self._schema_is_current(session):
                logger.info("Setting up Neo4j schema constraints and indexes.")
                self._migrate_to_v2(session)
                for cypher in SCHEMA_QUERIES:
                    try:
                        session.run(cypher)
                    except Exception as exc:
                        logger.warning("Schema query failed (may already exist): %s - %s", cypher[:60], exc)
                self._mark_schema_applied(session)
            else:
                logger.info(
                    "Schema already set up (version %d). Skipping constraints/indexes.", _SCHEMA_VERSION
                )

            if settings.economic_indicators_enabled:
                self._setup_economic_indicators(session)

        logger.info("Schema setup complete.")

    @staticmethod
    def _migrate_to_v2(session: Session) -> None:
        """Multi-portal migration: backfill source and drop legacy constraints.

        Idempotent: the backfill only touches nodes lacking a source, and the
        drops only fire on constraints that still exist. Runs batched implicit
        transactions, so it must not be wrapped in an explicit transaction.
        """
        for label in _V2_BACKFILL_LABELS:
            result = session.run(
                f"MATCH (n:{label}) WHERE n.source IS NULL "
                f"CALL (n) {{ SET n.source = 'comprar' }} "
                f"IN TRANSACTIONS OF 20000 ROWS"
            )
            summary = result.consume()
            updated = summary.counters.properties_set
            if updated:
                logger.info("v2 migration: backfilled source on %d %s nodes.", updated, label)

        legacy = {(label, prop) for label, prop in LEGACY_UNIQUE_CONSTRAINTS}
        for record in session.run(
            "SHOW CONSTRAINTS YIELD name, type, labelsOrTypes, properties "
            "WHERE type = 'UNIQUENESS' RETURN name, labelsOrTypes, properties"
        ):
            labels = record["labelsOrTypes"] or []
            props = record["properties"] or []
            if len(labels) == 1 and len(props) == 1 and (labels[0], props[0]) in legacy:
                logger.info("v2 migration: dropping legacy constraint %s.", record["name"])
                session.run(f"DROP CONSTRAINT {record['name']} IF EXISTS")

    @staticmethod
    def _schema_is_current(session: Session) -> bool:
        """Return True if the schema marker matches the current version.

        Checks label existence first via `db.labels()` to avoid spurious Neo4j
        warnings when the marker node has never been created.
        """
        label_row = session.run(
            "CALL db.labels() YIELD label WHERE label = '_SchemaMeta' RETURN true AS exists"
        ).single()
        if not label_row:
            return False
        record = session.run(
            "MATCH (m:_SchemaMeta {key: 'schema'}) RETURN m.version AS version"
        ).single()
        return record is not None and record["version"] == _SCHEMA_VERSION

    @staticmethod
    def _mark_schema_applied(session: Session) -> None:
        """Upsert the schema marker node with the current version and timestamp."""
        session.run(
            "MERGE (m:_SchemaMeta {key: 'schema'}) "
            "SET m.version = $version, m.applied_at = datetime()",
            {"version": _SCHEMA_VERSION},
        )

    def _setup_economic_indicators(self, session: Session) -> None:
        """Fetch and upsert inflation and FX indicator nodes from the full history."""
        self._fetch_and_merge_indicators(session, self._configured_start_date())

    def refresh_economic_indicators(self, lookback_days: int = 40) -> None:
        """Re-fetch the most recent inflation and FX observations and upsert them.

        The inflation adjustment used downstream reindexes nominal amounts to
        the latest available InflationIndex period, so as INDEC/BCRA publish
        new months the stored nodes must advance for "the most recent date" to
        move forward. This fetches from a small `lookback_days` window before
        the latest stored observation (to absorb INDEC index revisions)
        through today and MERGEs the results, so it is safe to re-run.
        """
        with self._driver.session() as session:
            start_date = self._refresh_start_date(session, lookback_days)
            logger.info("Refreshing economic indicators from %s.", start_date.isoformat())
            self._fetch_and_merge_indicators(session, start_date)

    @staticmethod
    def _configured_start_date() -> date:
        """Resolve the configured economic-indicator history start, defaulting safely."""
        try:
            return date.fromisoformat(settings.economic_indicators_start_date)
        except ValueError:
            logger.warning(
                "Invalid economic_indicators_start_date=%s; using 2015-01-01.",
                settings.economic_indicators_start_date,
            )
            return date(2015, 1, 1)

    def _refresh_start_date(self, session: Session, lookback_days: int) -> date:
        """Earliest date to re-fetch: latest stored observation minus a lookback.

        Uses the older of the latest InflationIndex month and the latest
        ExchangeRate day so both series catch up. Falls back to the configured
        history start when no indicator nodes exist yet.
        """
        record = session.run(
            """
            OPTIONAL MATCH (idx:InflationIndex)
            WITH max(idx.period_start) AS latest_idx
            OPTIONAL MATCH (fx:ExchangeRate)
            RETURN latest_idx, max(fx.observed_date) AS latest_fx
            """
        ).single()

        latest_dates = [
            value.to_native()
            for value in (record["latest_idx"], record["latest_fx"])
            if value is not None
        ]
        if not latest_dates:
            return self._configured_start_date()
        return min(latest_dates) - timedelta(days=lookback_days)

    def _fetch_and_merge_indicators(self, session: Session, start_date: date) -> None:
        """Fetch indicators from `start_date` to today and upsert the nodes."""
        try:
            inflation_indexes, exchange_rates = EconomicIndicatorsClient().fetch(
                start_date=start_date,
                currencies=settings.economic_indicators_currencies,
            )
        except Exception as exc:
            logger.error("Economic indicator refresh failed: %s", exc, exc_info=True)
            return

        def _tx(tx: Any) -> None:
            if inflation_indexes:
                self._run(tx, *IndicatorQueryBuilder.batch_merge_inflation_indexes(inflation_indexes))
            if exchange_rates:
                self._run(tx, *IndicatorQueryBuilder.batch_merge_exchange_rates(exchange_rates))

        session.execute_write(_tx)
        logger.info(
            "Economic indicators loaded: %d inflation indexes, %d FX rates.",
            len(inflation_indexes),
            len(exchange_rates),
        )

    def ingest_batch(self, results: list[ProcessResult]) -> None:
        """Ingest a batch of ProcessResult objects, one write transaction per result."""
        with self._driver.session() as session:
            for result in results:
                self._ingest_one(session, result)

    def _ingest_one(self, session: Session, result: ProcessResult) -> None:
        """Persist all nodes and relationships for a single ProcessResult."""
        pn = result.process.process_number
        logger.info("Ingesting process %s into Neo4j.", pn)

        for attempt in range(1, _TRANSIENT_RETRIES + 2):
            try:
                session.execute_write(self._ingest_one_tx, result)
                return
            except (TransientError, ServiceUnavailable) as exc:
                if attempt > _TRANSIENT_RETRIES:
                    logger.error("Failed ingesting process %s after retries: %s", pn, exc, exc_info=True)
                    return
                import time
                wait = 2 ** attempt
                logger.warning(
                    "Transient Neo4j error while ingesting %s (attempt %d/%d). Retrying in %ds: %s",
                    pn, attempt, _TRANSIENT_RETRIES, wait, exc,
                )
                time.sleep(wait)
            except Exception as exc:
                logger.error("Failed ingesting process %s: %s", pn, exc, exc_info=True)
                return

    def _ingest_one_tx(self, tx: Any, result: ProcessResult) -> None:
        """Transaction callback: persist all nodes/rels for one ProcessResult.

        Steps are ordered so every MERGE has its endpoints already in scope.
        """
        pn = result.process.process_number

        # 0. Cross-source collision guard: process numbers are only verified
        # unique within a portal, so never overwrite a process scraped from
        # the other portal.
        incoming_source = result.process.source or "comprar"
        record = tx.run(
            "MATCH (p:Process {process_number: $pn}) "
            "RETURN coalesce(p.source, 'comprar') AS src",
            {"pn": pn},
        ).single()
        if record and record["src"] != incoming_source:
            logger.error(
                "SOURCE COLLISION: process %s already exists with source=%s; "
                "skipping ingestion of the %s version. Resolve manually.",
                pn, record["src"], incoming_source,
            )
            return

        # 1. Process (single node).
        self._run(tx, *NodeQueryBuilder.merge_process(result.process))

        # 2. Organization (single, optional).
        if result.organization:
            self._run(tx, *NodeQueryBuilder.merge_organization(result.organization))
            self._merge_contacts_single(
                tx, "Organization", "saf_code",
                result.organization.saf_code,
                result.organization.address,
                result.organization.phone,
                result.organization.email,
            )

        # 3. ContractingUnit plus rels (single, optional).
        if result.contracting_unit:
            unit = result.contracting_unit
            unit_source = unit.source or incoming_source
            self._run(tx, *NodeQueryBuilder.merge_contracting_unit(unit))
            self._run(tx, *NodeQueryBuilder.rel_managed_by(pn, unit.code, unit_source))
            if unit.saf_code is not None:
                self._run(tx, *NodeQueryBuilder.rel_belongs_to(
                    unit.code, unit_source, unit.saf_code
                ))
            self._merge_contacts_single(
                tx, "ContractingUnit", "code",
                unit.code,
                unit.address,
                unit.phone,
                unit.email,
                extra_props={"source": unit_source},
            )

        if result.line_items:
            self._run(tx, *BatchQueryBuilder.batch_merge_line_items(result.line_items))

        if result.procurement_requests:
            self._run(tx, *BatchQueryBuilder.batch_merge_procurement_requests(result.procurement_requests))

        if result.penalties:
            self._run(tx, *BatchQueryBuilder.batch_merge_penalties(result.penalties))

        if result.gde_documents:
            self._run(tx, *BatchQueryBuilder.batch_merge_gde_documents(result.gde_documents))

        if result.providers:
            self._run(tx, *BatchQueryBuilder.batch_merge_providers(result.providers))
            self._merge_contacts_batch(
                tx, "Provider", "cuit",
                [(p.cuit, p.address, p.phone, p.email) for p in result.providers],
            )

        if result.invites:
            self._run(tx, *BatchQueryBuilder.batch_create_invites(result.invites))

        if result.bids:
            self._run(tx, *BatchQueryBuilder.batch_merge_bids(result.bids))

        if result.bid_lines:
            self._run(tx, *BatchQueryBuilder.batch_merge_bid_lines(result.bid_lines))

        if result.authorizers:
            self._run(tx, *BatchQueryBuilder.batch_merge_authorizers(result.authorizers))

        if result.contractual_documents:
            self._run(tx, *BatchQueryBuilder.batch_merge_contractual_documents(result.contractual_documents))

        if result.contract_lines:
            self._run(tx, *BatchQueryBuilder.batch_merge_contract_lines(result.contract_lines, pn))

        if result.provision_requests:
            self._run(tx, *BatchQueryBuilder.batch_merge_provision_requests(
                result.provision_requests, incoming_source))
            fulfilled = [
                (s.request_number, s.provider_cuit)
                for s in result.provision_requests if s.provider_cuit
            ]
            if fulfilled:
                self._run(tx, *BatchQueryBuilder.batch_rel_fulfilled_by(fulfilled))

        if result.provision_request_lines:
            self._run(tx, *BatchQueryBuilder.batch_merge_provision_request_lines(result.provision_request_lines))
            triples = [
                (prl.request_number, prl.line_number, pn)
                for prl in result.provision_request_lines
            ]
            if triples:
                self._run(tx, *BatchQueryBuilder.batch_rel_provision_line_for_line_item(triples))

        # Dictamen and DictamenSigner nodes must precede the edges (evaluations,
        # pre-adjudications, rejections) that MATCH them.
        if result.dictamenes:
            self._run(tx, *BatchQueryBuilder.batch_merge_dictamenes(result.dictamenes, incoming_source))
        if result.dictamen_signers:
            self._run(tx, *BatchQueryBuilder.batch_merge_dictamen_signers(result.dictamen_signers))

        self._ingest_authorizations_cd(tx, result)
        self._ingest_authorizations_spr(tx, result)
        self._ingest_evaluations(tx, result, incoming_source)
        self._ingest_pre_adjudications(tx, result, incoming_source)
        self._ingest_rejections(tx, result, incoming_source)

        # Economic context relationships (InflationIndex / ExchangeRate).
        # ars_historico is stored on each relationship, not on the price node.
        if settings.economic_indicators_enabled:
            for query, params in EconomicRelationshipBuilder().build_batches(result):
                self._run(tx, query, params)

    def _ingest_authorizations_cd(self, tx: Any, result: ProcessResult) -> None:
        """Persist AUTHORIZED_BY relationships for ContractualDocuments."""
        source = result.process.source or "comprar"
        batch_data = []
        for idx, (doc_num, rel_props) in enumerate(result.authorizations_cd):
            authorizer_name = rel_props.authorizer_name
            if not authorizer_name and idx < len(result.authorizers):
                authorizer_name = result.authorizers[idx].full_name
            if authorizer_name:
                batch_data.append({
                    "dn": doc_num,
                    "src": source,
                    "an": authorizer_name,
                    "rp": {k: v for k, v in rel_props.model_dump().items() if v is not None},
                })
        if batch_data:
            self._run(tx, *BatchQueryBuilder.batch_authorized_by_cd(batch_data))

    def _ingest_evaluations(self, tx: Any, result: ProcessResult, source: str) -> None:
        """Persist EVALUATED_BY relationships (dictamen evaluation committee)."""
        batch_data = [
            {
                "pn": ev.process_number,
                "src": source,
                "seq": ev.dictamen_sequence,
                "un": ev.username,
                "rp": {k: v for k, v in ev.model_dump().items()
                       if v is not None and k not in (
                           "process_number", "dictamen_sequence", "username")},
            }
            for ev in result.evaluations
        ]
        if batch_data:
            self._run(tx, *BatchQueryBuilder.batch_evaluated_by(batch_data))

    def _ingest_pre_adjudications(self, tx: Any, result: ProcessResult, source: str) -> None:
        """Persist PRE_ADJUDICATES relationships (Dictamen -> Provider, per renglón)."""
        if result.pre_adjudications:
            self._run(tx, *BatchQueryBuilder.batch_pre_adjudicates(result.pre_adjudications, source))

    def _ingest_rejections(self, tx: Any, result: ProcessResult, source: str) -> None:
        """Persist REJECTED relationships (Dictamen -> Provider, discarded bidders)."""
        if result.rejections:
            self._run(tx, *BatchQueryBuilder.batch_rejected(result.rejections, source))

    def _ingest_authorizations_spr(self, tx: Any, result: ProcessResult) -> None:
        """Persist AUTHORIZED_BY relationships for ProvisionRequests."""
        batch_data = []
        for idx, (req_num, rel_props) in enumerate(result.authorizations_spr):
            authorizer_name = rel_props.authorizer_name
            if not authorizer_name and idx < len(result.authorizers):
                authorizer_name = result.authorizers[idx].full_name
            if authorizer_name:
                batch_data.append({
                    "rn": req_num,
                    "an": authorizer_name,
                    "rp": {k: v for k, v in rel_props.model_dump().items() if v is not None},
                })
        if batch_data:
            self._run(tx, *BatchQueryBuilder.batch_authorized_by_spr(batch_data))

    def _merge_contacts_single(
        self, tx: Any, entity_label: str, key_field: str,
        key_value: Any, address: Optional[str], phone: Optional[str], email: Optional[str],
        extra_props: Optional[dict] = None,
    ) -> None:
        """Merge contacts for a single entity (Organization / ContractingUnit).

        Args:
            extra_props: Additional properties required to match the entity
                node (e.g. ``{"source": ...}`` for ContractingUnit, whose key
                is per-portal).
        """
        extra_props = extra_props or {}
        extra_match = "".join(f", {k}: $extra_{k}" for k in extra_props)
        extra_params = {f"extra_{k}": v for k, v in extra_props.items()}
        if address:
            n = _normalize_address(address)
            if n:
                tx.run(
                    f"MATCH (e:{entity_label} {{{key_field}: $ek{extra_match}}}) "
                    f"MERGE (a:Address {{value_key: $key}}) "
                    f"ON CREATE SET a.value = $value "
                    f"MERGE (e)-[:HAS_ADDRESS]->(a)",
                    {"ek": key_value, "key": n[1], "value": n[0], **extra_params},
                )
        if phone:
            n = _normalize_phone(phone)
            if n:
                tx.run(
                    f"MATCH (e:{entity_label} {{{key_field}: $ek{extra_match}}}) "
                    f"MERGE (p:Phone {{value_key: $key}}) "
                    f"ON CREATE SET p.value = $value "
                    f"MERGE (e)-[:HAS_PHONE]->(p)",
                    {"ek": key_value, "key": n[1], "value": n[0], **extra_params},
                )
        if email:
            n = _normalize_email(email)
            if n:
                tx.run(
                    f"MATCH (e:{entity_label} {{{key_field}: $ek{extra_match}}}) "
                    f"MERGE (em:Email {{value_key: $key}}) "
                    f"ON CREATE SET em.value = $value "
                    f"MERGE (e)-[:HAS_EMAIL]->(em)",
                    {"ek": key_value, "key": n[1], "value": n[0], **extra_params},
                )

    def _merge_contacts_batch(
        self, tx: Any, entity_label: str, key_field: str,
        entities_data: list[tuple],
    ) -> None:
        """Batch merge contacts for multiple entities (Providers) using UNWIND."""
        addresses: list[dict] = []
        phones: list[dict] = []
        emails: list[dict] = []

        for entity_key, address, phone, email in entities_data:
            if address:
                n = _normalize_address(address)
                if n:
                    addresses.append({"entity_key": entity_key, "value": n[0], "key": n[1]})
            if phone:
                n = _normalize_phone(phone)
                if n:
                    phones.append({"entity_key": entity_key, "value": n[0], "key": n[1]})
            if email:
                n = _normalize_email(email)
                if n:
                    emails.append({"entity_key": entity_key, "value": n[0], "key": n[1]})

        if addresses:
            tx.run(
                f"UNWIND $batch AS row "
                f"MATCH (e:{entity_label} {{{key_field}: row.entity_key}}) "
                f"MERGE (a:Address {{value_key: row.key}}) "
                f"ON CREATE SET a.value = row.value "
                f"MERGE (e)-[:HAS_ADDRESS]->(a)",
                {"batch": addresses},
            )
        if phones:
            tx.run(
                f"UNWIND $batch AS row "
                f"MATCH (e:{entity_label} {{{key_field}: row.entity_key}}) "
                f"MERGE (p:Phone {{value_key: row.key}}) "
                f"ON CREATE SET p.value = row.value "
                f"MERGE (e)-[:HAS_PHONE]->(p)",
                {"batch": phones},
            )
        if emails:
            tx.run(
                f"UNWIND $batch AS row "
                f"MATCH (e:{entity_label} {{{key_field}: row.entity_key}}) "
                f"MERGE (em:Email {{value_key: row.key}}) "
                f"ON CREATE SET em.value = row.value "
                f"MERGE (e)-[:HAS_EMAIL]->(em)",
                {"batch": emails},
            )

    def _run(self, tx: Any, query: str, params: dict) -> None:
        """Execute a single Cypher query inside the active transaction."""
        tx.run(query, params)
