"""
cypher_queries.py - Cypher MERGE/SET builders for ingesting scraped entities
into Neo4j.

Builders are grouped into cohesive classes:

  * ModelSerializer:   turn Pydantic models into Neo4j parameter dicts.
  * NodeQueryBuilder:  single header nodes (Process, Organization,
                       ContractingUnit) and their structural relationships.
  * BatchQueryBuilder: UNWIND-based bulk upserts for every collection-valued
                       entity, used by the ingestion layer to minimise
                       round-trips.

Design rules:

  * Always MERGE on the unique key to guarantee idempotency.
  * Use `SET node += $props` to upsert all non-key properties.
  * Relationships MATCH both endpoints by key, then MERGE the edge.

Every builder returns a `(query, params)` tuple ready for `session.run()`.
"""

from __future__ import annotations

from typing import Any

from scraper.models import (
    AuthorizerModel,
    BidLineModel,
    BidModel,
    ContractLineModel,
    ContractualDocumentModel,
    DictamenModel,
    DictamenSignerModel,
    GDEDocumentModel,
    InvitesRelProps,
    LineItemModel,
    OrganizationModel,
    PenaltyModel,
    PreAdjudicatesRelProps,
    ProcessModel,
    ProcurementRequestModel,
    ProviderModel,
    RejectedRelProps,
    ProvisionRequestLineModel,
    ProvisionRequestModel,
    ContractingUnitModel,
)
from utils.parsers import clean_text, normalize_currency


def _src(value: str | None) -> str:
    """Coalesce a model's source to the legacy default ("comprar").

    Pre-multi-portal data has no source property; "comprar" is the implied
    origin of every legacy node, and the schema migration backfills it.
    """
    return value or "comprar"


class ModelSerializer:
    """Convert Pydantic models into Neo4j-ready parameter dicts."""

    @staticmethod
    def props(model: Any, exclude_keys: set[str] | None = None) -> dict[str, Any]:
        """Dump a model to a dict, dropping None values and MERGE keys.

        String values are normalised with :func:`clean_text`; temporal values
        (date/datetime) are passed through so the driver stores native types.

        Args:
            model: A Pydantic model instance.
            exclude_keys: Field names to omit (typically the MERGE keys).

        Returns:
            A dict of property name to value, ready for ``SET node += $props``.
        """
        exclude_keys = exclude_keys or set()
        props: dict[str, Any] = {}
        for key, value in model.model_dump().items():
            if key in exclude_keys or value is None:
                continue
            if isinstance(value, str):
                normalized = normalize_currency(value) if "currency" in key else clean_text(value)
                if normalized is None:
                    continue
                props[key] = normalized
                continue
            props[key] = value
        return props


class NodeQueryBuilder:
    """Builders for the single header nodes of a process and their relationships."""

    @staticmethod
    def merge_process(process: ProcessModel) -> tuple[str, dict]:
        """Upsert the Process node keyed by ``process_number``."""
        query = """
        MERGE (p:Process {process_number: $key})
        SET p += $props
        """
        return query, {
            "key": process.process_number,
            "props": ModelSerializer.props(process, {"process_number"}),
        }

    @staticmethod
    def merge_organization(org: OrganizationModel) -> tuple[str, dict]:
        """Upsert the Organization node keyed by ``saf_code``."""
        query = """
        MERGE (o:Organization {saf_code: $key})
        SET o += $props
        """
        return query, {
            "key": org.saf_code,
            "props": ModelSerializer.props(org, {"saf_code"}),
        }

    @staticmethod
    def merge_contracting_unit(unit: ContractingUnitModel) -> tuple[str, dict]:
        """Upsert the ContractingUnit (UOC) node keyed by ``(code, source)``.

        UOC codes are per-portal registries: COMPR.AR's UOC "14" and
        CONTRAT.AR's UOC "14" are different offices.
        """
        query = """
        MERGE (u:ContractingUnit {code: $key, source: $src})
        SET u += $props
        """
        return query, {
            "key": unit.code,
            "src": _src(unit.source),
            "props": ModelSerializer.props(unit, {"code", "source", "saf_code"}),
        }

    @staticmethod
    def rel_managed_by(process_number: str, uoc_code: str, source: str | None) -> tuple[str, dict]:
        """Wire ``(Process)-[:MANAGED_BY]->(ContractingUnit)``."""
        query = """
        MATCH (p:Process {process_number: $pn})
        MATCH (u:ContractingUnit {code: $uc, source: $src})
        MERGE (p)-[:MANAGED_BY]->(u)
        """
        return query, {"pn": process_number, "uc": uoc_code, "src": _src(source)}

    @staticmethod
    def rel_belongs_to(uoc_code: str, source: str | None, saf_code: int) -> tuple[str, dict]:
        """Wire ``(ContractingUnit)-[:BELONGS_TO]->(Organization)``."""
        query = """
        MATCH (u:ContractingUnit {code: $uc, source: $src})
        MATCH (o:Organization {saf_code: $sc})
        MERGE (u)-[:BELONGS_TO]->(o)
        """
        return query, {"uc": uoc_code, "src": _src(source), "sc": saf_code}


class BatchQueryBuilder:
    """``UNWIND``-based bulk upserts for collection-valued entities."""

    @staticmethod
    def batch_merge_line_items(items: list[LineItemModel]) -> tuple[str, dict]:
        """Bulk-upsert LineItem nodes and link them to their Process."""
        query = """
        UNWIND $batch AS row
        MATCH (p:Process {process_number: row.pn})
        MERGE (li:LineItem {process_number: row.pn, line_number: row.ln})
        SET li += row.props
        MERGE (p)-[:HAS_LINE_ITEM]->(li)
        """
        return query, {"batch": [
            {"pn": i.process_number, "ln": i.line_number,
             "props": ModelSerializer.props(i, {"process_number", "line_number"})}
            for i in items
        ]}

    @staticmethod
    def batch_merge_procurement_requests(
        reqs: list[ProcurementRequestModel],
    ) -> tuple[str, dict]:
        """Bulk-upsert ProcurementRequest (SCO) nodes linked to their Process.

        Keyed by (request_number, source): SCO numbers are sequential per UOC
        and UOC code ranges overlap between portals.
        """
        query = """
        UNWIND $batch AS row
        MERGE (sc:ProcurementRequest {request_number: row.key, source: row.src})
        SET sc += row.props
        WITH sc, row
        MATCH (p:Process {process_number: row.pn})
        MERGE (p)-[:HAS_REQUEST]->(sc)
        """
        return query, {"batch": [
            {"key": r.request_number, "src": _src(r.source), "pn": r.process_number,
             "props": ModelSerializer.props(r, {"request_number", "source", "process_number"})}
            for r in reqs
        ]}

    @staticmethod
    def batch_merge_penalties(penalties: list[PenaltyModel]) -> tuple[str, dict]:
        """Bulk-upsert Penalty nodes keyed by (process_number, number)."""
        query = """
        UNWIND $batch AS row
        MATCH (p:Process {process_number: row.pn})
        MERGE (pen:Penalty {process_number: row.pn, number: row.num})
        SET pen += row.props
        MERGE (p)-[:HAS_PENALTY]->(pen)
        """
        return query, {"batch": [
            {"pn": p.process_number, "num": p.number,
             "props": ModelSerializer.props(p, {"process_number", "number"})}
            for p in penalties
        ]}

    @staticmethod
    def batch_merge_gde_documents(docs: list[GDEDocumentModel]) -> tuple[str, dict]:
        """Bulk-upsert GDEDocument nodes linked to their Process."""
        query = """
        UNWIND $batch AS row
        MERGE (gd:GDEDocument {gde_number: row.key})
        SET gd += row.props
        WITH gd, row
        MATCH (p:Process {process_number: row.pn})
        MERGE (p)-[:HAS_DOCUMENT]->(gd)
        """
        return query, {"batch": [
            {"key": d.gde_number, "pn": d.process_number,
             "props": ModelSerializer.props(d, {"gde_number", "process_number"})}
            for d in docs
        ]}

    @staticmethod
    def batch_merge_providers(providers: list[ProviderModel]) -> tuple[str, dict]:
        """Bulk-upsert Provider nodes keyed by ``cuit``."""
        query = """
        UNWIND $batch AS row
        MERGE (pr:Provider {cuit: row.key})
        SET pr += row.props
        """
        return query, {"batch": [
            {"key": p.cuit, "props": ModelSerializer.props(p, {"cuit"})}
            for p in providers
        ]}

    @staticmethod
    def batch_create_invites(invites: list[InvitesRelProps]) -> tuple[str, dict]:
        """Bulk-create ``(Process)-[:INVITES]->(Provider)`` relationships."""
        query = """
        UNWIND $batch AS row
        MATCH (p:Process {process_number: row.pn})
        MATCH (pr:Provider {cuit: row.cuit})
        MERGE (p)-[:INVITES]->(pr)
        """
        return query, {"batch": [
            {"pn": i.process_number, "cuit": i.provider_cuit}
            for i in invites
        ]}

    @staticmethod
    def batch_merge_bids(bids: list[BidModel]) -> tuple[str, dict]:
        """Bulk-upsert Bid nodes and link them to Process and Provider."""
        query = """
        UNWIND $batch AS row
        MATCH (p:Process {process_number: row.pn})
        MATCH (pr:Provider {cuit: row.cuit})
        MERGE (b:Bid {process_number: row.pn, provider_cuit: row.cuit})
        SET b += row.props
        MERGE (p)-[:HAS_BID]->(b)
        MERGE (b)-[:SUBMITTED_BY]->(pr)
        """
        return query, {"batch": [
            {"pn": b.process_number, "cuit": b.provider_cuit,
             "props": ModelSerializer.props(b, {"process_number", "provider_cuit"})}
            for b in bids
        ]}

    @staticmethod
    def batch_merge_bid_lines(lines: list[BidLineModel]) -> tuple[str, dict]:
        """Bulk-upsert BidLine nodes linked to their Bid and LineItem."""
        query = """
        UNWIND $batch AS row
        MATCH (b:Bid {process_number: row.pn, provider_cuit: row.cuit})
        MATCH (li:LineItem {process_number: row.pn, line_number: row.ln})
        MERGE (bl:BidLine {
            process_number: row.pn,
            provider_cuit: row.cuit,
            line_number: row.ln,
            alternative_number: row.alt
        })
        SET bl += row.props
        MERGE (b)-[:HAS_BID_LINE]->(bl)
        MERGE (bl)-[:FOR_LINE_ITEM]->(li)
        """
        return query, {"batch": [
            {"pn": l.process_number, "cuit": l.provider_cuit,
             "ln": l.line_number, "alt": l.alternative_number,
             "props": ModelSerializer.props(
                 l, {"process_number", "provider_cuit", "line_number", "alternative_number"})}
            for l in lines
        ]}

    @staticmethod
    def batch_merge_authorizers(auths: list[AuthorizerModel]) -> tuple[str, dict]:
        """Bulk-upsert Authorizer nodes keyed by ``full_name``."""
        query = """
        UNWIND $batch AS row
        MERGE (a:Authorizer {full_name: row.key})
        SET a += row.props
        """
        return query, {"batch": [
            {"key": a.full_name, "props": ModelSerializer.props(a, {"full_name"})}
            for a in auths
        ]}

    @staticmethod
    def batch_merge_contractual_documents(
        docs: list[ContractualDocumentModel],
    ) -> tuple[str, dict]:
        """Bulk-upsert ContractualDocument nodes linked to Process and Provider.

        Keyed by (document_number, source): document numbers are sequential per
        UOC and UOC code ranges overlap between portals.
        """
        query = """
        UNWIND $batch AS row
        MERGE (cd:ContractualDocument {document_number: row.key, source: row.src})
        SET cd += row.props
        WITH cd, row
        MATCH (p:Process {process_number: row.pn})
        MATCH (pr:Provider {cuit: row.cuit})
        MERGE (p)-[:GENERATES]->(cd)
        MERGE (cd)-[:AWARDED_TO]->(pr)
        """
        return query, {"batch": [
            {"key": d.document_number, "src": _src(d.source),
             "pn": d.process_number, "cuit": d.provider_cuit,
             "props": ModelSerializer.props(
                 d, {"document_number", "source", "process_number", "provider_cuit"})}
            for d in docs
        ]}

    @staticmethod
    def batch_merge_contract_lines(
        lines: list[ContractLineModel], process_number: str,
    ) -> tuple[str, dict]:
        """Bulk-upsert ContractLine nodes linked to their document and LineItem.

        Args:
            lines: Contract line models to upsert.
            process_number: Process the lines belong to, injected by the caller
                because it cannot be derived from the document number alone.
        """
        query = """
        UNWIND $batch AS row
        MATCH (cd:ContractualDocument {document_number: row.dn, source: row.src})
        MATCH (li:LineItem {process_number: row.pn, line_number: row.ln})
        MERGE (cl:ContractLine {
            document_number: row.dn,
            source: row.src,
            line_number: row.ln,
            alternative_number: row.alt
        })
        SET cl += row.props
        MERGE (cd)-[:HAS_CONTRACT_LINE]->(cl)
        MERGE (cl)-[:FOR_LINE_ITEM]->(li)
        """
        return query, {"batch": [
            {"dn": cl.document_number, "src": _src(cl.source), "pn": process_number,
             "ln": cl.line_number, "alt": cl.alternative_number or 1,
             "props": ModelSerializer.props(
                 cl, {"document_number", "source", "line_number", "alternative_number"})}
            for cl in lines
        ]}

    @staticmethod
    def batch_merge_provision_requests(
        sprs: list[ProvisionRequestModel], source: str | None,
    ) -> tuple[str, dict]:
        """Bulk-upsert ProvisionRequest (SPR) nodes linked to their OCA document.

        Args:
            sprs: Provision request models to upsert.
            source: Portal of the parent process (OCAs only exist on comprar,
                but the parent document key now includes its source).
        """
        query = """
        UNWIND $batch AS row
        MERGE (spr:ProvisionRequest {request_number: row.key})
        SET spr += row.props
        WITH spr, row
        MATCH (cd:ContractualDocument {document_number: row.oca, source: row.src})
        MERGE (cd)-[:HAS_PROVISION_REQUEST]->(spr)
        """
        return query, {"batch": [
            {"key": s.request_number, "oca": s.oca_number, "src": _src(source),
             "props": ModelSerializer.props(s, {"request_number", "oca_number", "provider_cuit"})}
            for s in sprs
        ]}

    @staticmethod
    def batch_rel_fulfilled_by(pairs: list[tuple[str, str]]) -> tuple[str, dict]:
        """Bulk-create ``(ProvisionRequest)-[:FULFILLED_BY]->(Provider)``."""
        query = """
        UNWIND $batch AS row
        MATCH (spr:ProvisionRequest {request_number: row.rn})
        MATCH (pr:Provider {cuit: row.cuit})
        MERGE (spr)-[:FULFILLED_BY]->(pr)
        """
        return query, {"batch": [{"rn": rn, "cuit": cuit} for rn, cuit in pairs]}

    @staticmethod
    def batch_merge_provision_request_lines(
        lines: list[ProvisionRequestLineModel],
    ) -> tuple[str, dict]:
        """Bulk-upsert ProvisionRequestLine nodes linked to their ProvisionRequest."""
        query = """
        UNWIND $batch AS row
        MATCH (spr:ProvisionRequest {request_number: row.rn})
        MERGE (prl:ProvisionRequestLine {
            request_number: row.rn,
            line_number: row.ln,
            alternative_number: row.alt
        })
        SET prl += row.props
        MERGE (spr)-[:HAS_PROVISION_LINE]->(prl)
        """
        return query, {"batch": [
            {"rn": l.request_number, "ln": l.line_number, "alt": l.alternative_number or 1,
             "props": ModelSerializer.props(
                 l, {"request_number", "line_number", "alternative_number"})}
            for l in lines
        ]}

    @staticmethod
    def batch_rel_provision_line_for_line_item(
        triples: list[tuple[str, int, str]],
    ) -> tuple[str, dict]:
        """Bulk-link ``(ProvisionRequestLine)-[:FOR_LINE_ITEM]->(LineItem)``."""
        query = """
        UNWIND $batch AS row
        MATCH (prl:ProvisionRequestLine {request_number: row.rn, line_number: row.ln})
        MATCH (li:LineItem {process_number: row.pn, line_number: row.ln})
        MERGE (prl)-[:FOR_LINE_ITEM]->(li)
        """
        return query, {"batch": [{"rn": rn, "ln": ln, "pn": pn} for rn, ln, pn in triples]}

    @staticmethod
    def batch_authorized_by_cd(data: list[dict]) -> tuple[str, dict]:
        """Bulk-create ``(ContractualDocument)-[:AUTHORIZED_BY]->(Authorizer)``.

        Args:
            data: Rows shaped ``{"dn": doc_number, "src": source, "an": auth_name,
                "rp": props}``.
        """
        query = """
        UNWIND $batch AS row
        MATCH (cd:ContractualDocument {document_number: row.dn, source: row.src})
        MATCH (a:Authorizer {full_name: row.an})
        MERGE (cd)-[r:AUTHORIZED_BY]->(a)
        SET r += row.rp
        """
        return query, {"batch": data}

    @staticmethod
    def batch_merge_dictamenes(
        dictamenes: list[DictamenModel], source: str | None,
    ) -> tuple[str, dict]:
        """Bulk-upsert Dictamen nodes linked to their Process.

        Keyed by (process_number, source, sequence): the portal exposes no
        stable identifier for the dictamen itself.
        """
        query = """
        UNWIND $batch AS row
        MATCH (p:Process {process_number: row.pn})
        MERGE (d:Dictamen {process_number: row.pn, source: row.src, sequence: row.seq})
        SET d += row.props
        MERGE (p)-[:HAS_DICTAMEN]->(d)
        """
        return query, {"batch": [
            {"pn": d.process_number, "src": _src(source), "seq": d.sequence,
             "props": ModelSerializer.props(d, {"process_number", "source", "sequence"})}
            for d in dictamenes
        ]}

    @staticmethod
    def batch_merge_dictamen_signers(signers: list[DictamenSignerModel]) -> tuple[str, dict]:
        """Bulk-upsert DictamenSigner nodes keyed by ``username``."""
        query = """
        UNWIND $batch AS row
        MERGE (s:DictamenSigner {username: row.key})
        SET s += row.props
        """
        return query, {"batch": [
            {"key": s.username, "props": ModelSerializer.props(s, {"username"})}
            for s in signers
        ]}

    @staticmethod
    def batch_evaluated_by(data: list[dict]) -> tuple[str, dict]:
        """Bulk-create ``(Dictamen)-[:EVALUATED_BY]->(DictamenSigner)``.

        Sourced from the CONTRAT.AR pre-award opinion signers grid.

        Args:
            data: Rows shaped ``{"pn": process_number, "src": source,
                "seq": dictamen_sequence, "un": username, "rp": props}``.
        """
        query = """
        UNWIND $batch AS row
        MATCH (d:Dictamen {process_number: row.pn, source: row.src, sequence: row.seq})
        MATCH (s:DictamenSigner {username: row.un})
        MERGE (d)-[r:EVALUATED_BY]->(s)
        SET r += row.rp
        """
        return query, {"batch": data}

    @staticmethod
    def batch_pre_adjudicates(
        rels: list[PreAdjudicatesRelProps], source: str | None,
    ) -> tuple[str, dict]:
        """Bulk-create ``(Dictamen)-[:PRE_ADJUDICATES]->(Provider)`` per renglón.

        One edge per (line_number, alternative_number) so a dictamen can
        recommend the same provider across several lines without collapsing.
        """
        query = """
        UNWIND $batch AS row
        MATCH (d:Dictamen {process_number: row.pn, source: row.src, sequence: row.seq})
        MATCH (pr:Provider {cuit: row.cuit})
        MERGE (d)-[r:PRE_ADJUDICATES {
            line_number: row.ln,
            alternative_number: row.alt
        }]->(pr)
        SET r += row.props
        """
        return query, {"batch": [
            {"pn": r.process_number, "src": _src(source), "seq": r.dictamen_sequence,
             "cuit": r.provider_cuit,
             "ln": r.line_number if r.line_number is not None else -1,
             "alt": r.alternative_number if r.alternative_number is not None else -1,
             "props": ModelSerializer.props(
                 r, {"process_number", "dictamen_sequence", "provider_cuit"})}
            for r in rels
        ]}

    @staticmethod
    def batch_rejected(
        rels: list[RejectedRelProps], source: str | None,
    ) -> tuple[str, dict]:
        """Bulk-create ``(Dictamen)-[:REJECTED]->(Provider)``, one per provider."""
        query = """
        UNWIND $batch AS row
        MATCH (d:Dictamen {process_number: row.pn, source: row.src, sequence: row.seq})
        MATCH (pr:Provider {cuit: row.cuit})
        MERGE (d)-[r:REJECTED]->(pr)
        SET r += row.props
        """
        return query, {"batch": [
            {"pn": r.process_number, "src": _src(source), "seq": r.dictamen_sequence,
             "cuit": r.provider_cuit,
             "props": ModelSerializer.props(
                 r, {"process_number", "dictamen_sequence", "provider_cuit"})}
            for r in rels
        ]}

    @staticmethod
    def batch_authorized_by_spr(data: list[dict]) -> tuple[str, dict]:
        """Bulk-create ``(ProvisionRequest)-[:AUTHORIZED_BY]->(Authorizer)``.

        Args:
            data: Rows shaped ``{"rn": req_number, "an": auth_name, "rp": props}``.
        """
        query = """
        UNWIND $batch AS row
        MATCH (spr:ProvisionRequest {request_number: row.rn})
        MATCH (a:Authorizer {full_name: row.an})
        MERGE (spr)-[r:AUTHORIZED_BY]->(a)
        SET r += row.rp
        """
        return query, {"batch": data}


# Single-property unique constraints replaced by per-source composite keys in
# schema v2. The client drops them (by label/property introspection) during the
# v2 migration.
LEGACY_UNIQUE_CONSTRAINTS: list[tuple[str, str]] = [
    ("ContractingUnit", "code"),
    ("ProcurementRequest", "request_number"),
    ("ContractualDocument", "document_number"),
]

SCHEMA_QUERIES: list[str] = [
    # Uniqueness constraints. Process numbers stay globally unique (verified
    # disjoint across portals; a cross-source guard at ingestion enforces it),
    # while UOC codes, SCO numbers and contractual-document numbers are only
    # unique within a portal, hence the (key, source) composites.
    "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Process) REQUIRE p.process_number IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (o:Organization) REQUIRE o.saf_code IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (u:ContractingUnit) REQUIRE (u.code, u.source) IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (pr:Provider) REQUIRE pr.cuit IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (cd:ContractualDocument) REQUIRE (cd.document_number, cd.source) IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (gd:GDEDocument) REQUIRE gd.gde_number IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (sc:ProcurementRequest) REQUIRE (sc.request_number, sc.source) IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (spr:ProvisionRequest) REQUIRE spr.request_number IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Dictamen) REQUIRE (d.process_number, d.source, d.sequence) IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (s:DictamenSigner) REQUIRE s.username IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (a:Authorizer) REQUIRE a.full_name IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (a:Address) REQUIRE a.value_key IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Phone) REQUIRE p.value_key IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (e:Email) REQUIRE e.value_key IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (idx:InflationIndex) REQUIRE (idx.series_id, idx.period) IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (fx:ExchangeRate) REQUIRE (fx.currency, fx.observed_date, fx.rate_type) IS UNIQUE",
    # Indexes
    "CREATE INDEX IF NOT EXISTS FOR (a:Authorizer) ON (a.document_number)",
    "CREATE INDEX IF NOT EXISTS FOR (p:Process) ON (p.status)",
    "CREATE INDEX IF NOT EXISTS FOR (p:Process) ON (p.selection_procedure)",
    "CREATE INDEX IF NOT EXISTS FOR (p:Process) ON (p.opening_date)",
    "CREATE INDEX IF NOT EXISTS FOR (p:Process) ON (p.process_type_code)",
    "CREATE INDEX IF NOT EXISTS FOR (pr:Provider) ON (pr.business_name)",
    "CREATE INDEX IF NOT EXISTS FOR (bl:BidLine) ON (bl.is_adjudicated)",
    "CREATE INDEX IF NOT EXISTS FOR (cd:ContractualDocument) ON (cd.document_type)",
    "CREATE INDEX IF NOT EXISTS FOR (cd:ContractualDocument) ON (cd.status)",
    "CREATE INDEX IF NOT EXISTS FOR (spr:ProvisionRequest) ON (spr.status)",
    "CREATE INDEX IF NOT EXISTS FOR (a:Address) ON (a.value)",
    "CREATE INDEX IF NOT EXISTS FOR (p:Phone) ON (p.value)",
    "CREATE INDEX IF NOT EXISTS FOR (e:Email) ON (e.value)",
    "CREATE INDEX IF NOT EXISTS FOR (idx:InflationIndex) ON (idx.period)",
    "CREATE INDEX IF NOT EXISTS FOR (idx:InflationIndex) ON (idx.period_start)",
    "CREATE INDEX IF NOT EXISTS FOR (fx:ExchangeRate) ON (fx.currency)",
    "CREATE INDEX IF NOT EXISTS FOR (fx:ExchangeRate) ON (fx.observed_date)",
    # Per-source filters
    "CREATE INDEX IF NOT EXISTS FOR (p:Process) ON (p.source)",
    # Composite indexes for multi-key MERGE performance
    "CREATE INDEX IF NOT EXISTS FOR (li:LineItem) ON (li.process_number, li.line_number)",
    "CREATE INDEX IF NOT EXISTS FOR (b:Bid) ON (b.process_number, b.provider_cuit)",
    "CREATE INDEX IF NOT EXISTS FOR (bl:BidLine) ON (bl.process_number, bl.provider_cuit, bl.line_number, bl.alternative_number)",
    "CREATE INDEX IF NOT EXISTS FOR (cl:ContractLine) ON (cl.document_number, cl.source, cl.line_number, cl.alternative_number)",
    "CREATE INDEX IF NOT EXISTS FOR (prl:ProvisionRequestLine) ON (prl.request_number, prl.line_number, prl.alternative_number)",
    "CREATE INDEX IF NOT EXISTS FOR (pen:Penalty) ON (pen.process_number, pen.number)",
    "CREATE INDEX IF NOT EXISTS FOR (d:Dictamen) ON (d.process_number, d.source, d.sequence)",
]
