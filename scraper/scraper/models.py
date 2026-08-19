"""
models.py - Pydantic data models for the scraper.

One model per Neo4j node type and one model for each relationship-property
shape, matching the schema defined in neo4j_schema.md exactly. Numeric
section markers below (5.1, 5.2, ...) refer to that schema document.

All fields are Optional by default because scraping is inherently partial:
pages may not expose every field (e.g. a Deserted process has no bids).
Required key fields are flagged inline and validated as non-None at the
ingestion layer before MERGE operations.

Relationship-property classes are at the bottom of the file.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# 5.1 Process

class ProcessModel(BaseModel):
    """Central node. One per procurement process."""
    process_number: str                             # KEY
    source: Optional[str] = None                    # "comprar" | "contratar"
    file_number: Optional[str] = None
    descriptive_name: Optional[str] = None
    object_of_procurement: Optional[str] = None
    selection_procedure: Optional[str] = None
    process_type_code: Optional[str] = None         # e.g. "LPR", "CDI"
    modality: Optional[str] = None
    stage: Optional[str] = None
    scope: Optional[str] = None
    legal_framework: List[str] = Field(default_factory=list)
    currencies: List[str] = Field(default_factory=list)
    quotation_type: Optional[str] = None
    award_type: Optional[str] = None
    generated_document_type: Optional[str] = None
    status: Optional[str] = None
    reception_address: Optional[str] = None
    offer_maintenance_days: Optional[int] = None
    requires_payment: Optional[bool] = None
    generates_resources: Optional[bool] = None
    external_financing: Optional[bool] = None
    accepts_extension: Optional[bool] = None
    accepts_price_adjustment: Optional[bool] = None
    scheduled_portal_publish_date: Optional[datetime] = None
    official_gazette_publish_date: Optional[datetime] = None
    inquiry_start_date: Optional[datetime] = None
    inquiry_end_date: Optional[datetime] = None
    days_to_publish: Optional[int] = None
    opening_date: Optional[datetime] = None
    participating_providers_count: Optional[int] = None
    confirmed_offers_count: Optional[int] = None
    # Public-works (CONTRAT.AR) specific fields.
    contracting_system: Optional[str] = None        # "Sistema de Contratación"
    financial_advance: Optional[str] = None         # "Anticipo Financiero", e.g. "30%"
    requires_repair_fund: Optional[bool] = None     # "Requiere fondo de reparo"
    includes_price_improvement: Optional[bool] = None  # "Incluye mejora de propuestas en Apertura"
    source_url: Optional[str] = None
    offers_url: Optional[str] = None
    scraped_at: Optional[datetime] = None


# 5.2 Organization (SAF)

class OrganizationModel(BaseModel):
    """Top-level public entity (Servicio Administrativo Financiero)."""
    saf_code: int                                   # KEY
    name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


# 5.3 ContractingUnit (UOC)

class ContractingUnitModel(BaseModel):
    """Unidad Operativa de Contrataciones.

    Keyed by (code, source): UOC codes are per-portal registries and the same
    numeric code names different offices on COMPR.AR and CONTRAT.AR.
    """
    code: str                                       # KEY (with source), e.g. "101-000", "14/3"
    source: Optional[str] = None                    # KEY (with code)
    name: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    province: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    saf_code: Optional[int] = Field(
        None,
        description="FK to Organization, used for BELONGS_TO rel. None when the "
                    "page exposes no SAF (contratar process numbers carry a UOC "
                    "code, not a SAF, so no fallback applies there).",
    )


# 5.4 Provider

class ProviderModel(BaseModel):
    """Supplier / bidder registered in SIPRO."""
    cuit: str                                       # KEY
    business_name: Optional[str] = None
    sipro_entity_id: Optional[int] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    province: Optional[str] = None
    phone: Optional[str] = None
    fax: Optional[str] = None
    email: Optional[str] = None
    sipro_status: Optional[str] = None


# 5.5 LineItem

class LineItemModel(BaseModel):
    """One renglón declared in the process pliego."""
    process_number: str                             # FK, used for HAS_LINE_ITEM rel
    line_number: int
    subtotal: Optional[float] = None                # CONTRAT.AR: official budget per renglón
    expenditure_object: Optional[str] = None
    catalog_code: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_of_measure: Optional[str] = None
    observations: Optional[str] = None
    specifications: Optional[str] = None
    delivery_details: Optional[str] = None
    is_grouped_item: Optional[bool] = None


# 5.6 ProcurementRequest (SCO)

class ProcurementRequestModel(BaseModel):
    """Solicitud de Contratación, internal purchasing request.

    Keyed by (request_number, source): SCO numbers are sequential per UOC and
    UOC code ranges overlap between portals, so cross-portal collisions are
    likely.
    """
    request_number: str                             # KEY (with source)
    source: Optional[str] = None                    # KEY (with request_number)
    process_number: str                             # FK, used for HAS_REQUEST rel
    status: Optional[str] = None
    executing_unit: Optional[str] = None
    category: Optional[str] = None
    urgency_type: Optional[str] = None
    created_at: Optional[date] = None


# 5.7 Bid

class BidModel(BaseModel):
    """One offer per provider per process, from the comparative table."""
    process_number: str                             # FK, used for HAS_BID rel
    provider_cuit: str                              # FK, used for SUBMITTED_BY rel
    status: Optional[str] = None
    rejection_reason: Optional[str] = None
    submitted_at: Optional[datetime] = None
    total_amount: Optional[float] = None
    currency: Optional[str] = None
    # CONTRAT.AR opening act: proposal guarantee details.
    guarantee_type: Optional[str] = None
    guarantee_form: Optional[str] = None
    guarantee_amount: Optional[float] = None


# 5.8 BidLine

class BidLineModel(BaseModel):
    """One renglón x alternative combination within a bid."""
    process_number: str                             # used to link back to HAS_BID
    provider_cuit: str                              # used to identify the parent Bid
    line_number: int
    alternative_number: int
    catalog_code: Optional[str] = None
    description: Optional[str] = None
    requested_quantity: Optional[float] = None
    offered_quantity: Optional[float] = None
    unit_of_measure: Optional[str] = None
    unit_price: Optional[float] = None
    total_per_line: Optional[float] = None
    currency: Optional[str] = None
    technical_specifications: Optional[str] = None
    is_national_good: Optional[bool] = None
    is_adjudicated: Optional[bool] = None


# 5.9 ContractualDocument

class ContractualDocumentModel(BaseModel):
    """A finalized Purchase Order (OC), Open Purchase Order (OCA) or public
    works Contract (CON).

    Keyed by (document_number, source): document numbers are sequential per
    UOC and UOC code ranges overlap between portals.
    """
    document_number: str                            # KEY (with source)
    source: Optional[str] = None                    # KEY (with document_number)
    process_number: str
    provider_cuit: str
    document_type: Optional[str] = None
    revision_type: Optional[str] = None             # CONTRAT.AR: "Original" / "Ampliación"
    status: Optional[str] = None
    authorization_date: Optional[date] = None       # CONTRAT.AR: "Fecha autorización"
    perfection_date: Optional[date] = None
    total_amount: Optional[float] = None
    current_amount: Optional[float] = None          # CONTRAT.AR: "Importe Vigente"
    variation_pct: Optional[float] = None           # CONTRAT.AR: "Porcentaje Variación"
    award_act_number: Optional[str] = None          # CONTRAT.AR: GDE number of the award act
    observations: Optional[str] = None              # CONTRAT.AR: free-text block under the detail table (may name officials)
    currency: Optional[str] = None
    delivery_start_date: Optional[date] = None
    contract_duration: Optional[str] = None
    max_extendable_amount: Optional[float] = None
    extension_currency: Optional[str] = None
    confirmed_extensions_count: Optional[int] = None
    available_extension_amount: Optional[float] = None
    available_extension_pct: Optional[float] = None
    max_extendable_periods: Optional[float] = None
    extension_period_currency: Optional[str] = None
    available_extension_period_pct: Optional[float] = None
    source_url: Optional[str] = None
    scraped_at: Optional[datetime] = None


# 5.10 ContractLine

class ContractLineModel(BaseModel):
    """Each renglón inside a ContractualDocument."""
    document_number: str                            # FK, used for HAS_CONTRACT_LINE
    source: Optional[str] = None                    # part of the key (parent doc is per-source)
    line_number: int
    alternative_number: Optional[int] = None
    catalog_code: Optional[str] = None
    description: Optional[str] = None
    awarded_quantity: Optional[float] = None
    unit_of_measure: Optional[str] = None
    unit_price: Optional[float] = None
    total_price: Optional[float] = None
    currency: Optional[str] = None
    delivery_address: Optional[str] = None
    delivery_term: Optional[str] = None
    observations: Optional[str] = None
    min_quantity: Optional[float] = None            # OCA only
    max_quantity: Optional[float] = None            # OCA only


# 5.11 ProvisionRequest (SPR)

class ProvisionRequestModel(BaseModel):
    """Solicitud de Provisión, call-off against an OCA."""
    request_number: str                             # KEY
    oca_number: str                                 # FK, used for HAS_PROVISION_REQUEST
    process_number: Optional[str] = None
    file_number: Optional[str] = None
    created_at: Optional[datetime] = None
    status: Optional[str] = None
    saf_code: Optional[int] = None
    saf_name: Optional[str] = None
    requesting_unit: Optional[str] = None
    descriptive_name: Optional[str] = None
    object_description: Optional[str] = None
    provider_cuit: Optional[str] = None             # FK, used for FULFILLED_BY
    total_amount: Optional[float] = None
    currency: Optional[str] = None
    source_url: Optional[str] = None
    scraped_at: Optional[datetime] = None


# 5.12 ProvisionRequestLine

class ProvisionRequestLineModel(BaseModel):
    """Each item row inside a Solicitud de Provisión."""
    request_number: str                             # FK, used for HAS_PROVISION_LINE
    line_number: int
    alternative_number: Optional[int] = None
    catalog_code: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_of_measure: Optional[str] = None
    unit_price: Optional[float] = None
    currency: Optional[str] = None
    total_price: Optional[float] = None


# 5.15 Economic indicators

class InflationIndexModel(BaseModel):
    """Monthly inflation index observation used to contextualize amounts."""
    series_id: str
    period: str                                      # YYYY-MM
    period_start: date
    period_end: date
    index_value: float
    base: Optional[str] = None
    source: Optional[str] = None
    source_url: Optional[str] = None
    fetched_at: Optional[datetime] = None


class ExchangeRateModel(BaseModel):
    """Daily ARS-per-currency exchange rate observation."""
    currency: str
    observed_date: date
    rate_type: str
    ars_per_unit: float
    source: Optional[str] = None
    source_url: Optional[str] = None
    fetched_at: Optional[datetime] = None


# 5.13 Authorizer

class AuthorizerModel(BaseModel):
    """Government official who authorizes a ContractualDocument or SPR."""
    full_name: str                                  # KEY, upper-cased
    document_type: Optional[str] = None
    document_number: Optional[str] = None


# 5.14 GDEDocument

class GDEDocumentModel(BaseModel):
    """Any GDE-system document attached to a process."""
    gde_number: str                                 # KEY
    process_number: str                             # FK, used for HAS_DOCUMENT
    document_type: Optional[str] = None
    special_number: Optional[str] = None
    linked_at: Optional[date] = None
    status: Optional[str] = None


# 5.16 Penalty

class PenaltyModel(BaseModel):
    """Penalty clause defined in the process."""
    process_number: str                             # FK, used for HAS_PENALTY
    number: Optional[int] = None
    description: Optional[str] = None


# 5.17 Dictamen (CONTRAT.AR pre-award opinion)

class DictamenModel(BaseModel):
    """A pre-award opinion (dictamen de preadjudicación).

    Keyed by (process_number, source, sequence). The portal exposes no stable
    identifier for the dictamen itself, so `sequence` is the 1-based order of
    the dictamen among the process's pre-award opinions.
    """
    process_number: str                             # KEY (with source, sequence)
    source: Optional[str] = None                    # KEY
    sequence: int = 1                               # KEY
    issue_date: Optional[datetime] = None           # lblFechaPublicacionTitulo
    pre_awarded_to: Optional[str] = None            # overall recommended winner (lblRazonSocial)
    pre_award_total: Optional[float] = None         # lblCantPrecioTotalPreAdjudicacion
    currency: Optional[str] = None
    offers_count: Optional[int] = None              # lblNumeroOfertasPresentadas
    legal_framework: Optional[str] = None           # txtEncuadre
    budget_imputation: Optional[str] = None         # txtImputacion
    source_url: Optional[str] = None
    scraped_at: Optional[datetime] = None


# 5.18 DictamenSigner

class DictamenSignerModel(BaseModel):
    """A member of a dictamen's evaluation committee.

    Identified by the portal `username` shown in the signers grid (a raw CUIT
    when the portal exposes no username). Kept distinct from `Authorizer` on
    purpose: dictamen signers are portal usernames, a different identity space
    from the named-and-DNI'd officials who sign contractual documents.
    """
    username: str                                   # KEY


# Relationship property models

class AuthorizedByRelProps(BaseModel):
    """Properties carried on the AUTHORIZED_BY relationship.

    Set on both ContractualDocument->Authorizer and ProvisionRequest->Authorizer.
    """
    authorizer_name: Optional[str] = None
    authorizer_type: Optional[str] = None           # e.g. "Presupuestario"
    role: Optional[str] = None                      # e.g. "Titular de Entidad"
    executing_unit: Optional[str] = None            # SPR only
    authorized_at: Optional[datetime] = None


class InvitesRelProps(BaseModel):
    """Represents a single INVITES relationship: Process -> Provider. CDI/LPU only."""
    process_number: str
    provider_cuit: str


class EvaluatedByRelProps(BaseModel):
    """One EVALUATED_BY relationship: Dictamen -> DictamenSigner.

    Sourced from the CONTRAT.AR pre-award opinion (dictamen) signers grid.
    `username` is the signer's portal username (a raw CUIT when the portal
    exposes none) and keys the DictamenSigner node; `dictamen_sequence`
    identifies the parent Dictamen node. `role` and `status` describe this
    signer's participation in this dictamen, so they live on the relationship.
    """
    process_number: str
    dictamen_sequence: int = 1
    username: str
    role: Optional[str] = None                      # e.g. "Administrativo"
    status: Optional[str] = None                    # e.g. "Autorizada"


class PreAdjudicatesRelProps(BaseModel):
    """One PRE_ADJUDICATES relationship: Dictamen -> Provider, per renglón.

    Sourced from the dictamen pre-adjudication grid (the committee's
    recommended winner per line, `is_primary=True`) and the secondary-offers
    grid (merit-ordered runners-up, `is_primary=False`). `provider_cuit` is
    resolved by the orchestrator from the process's already-scraped providers,
    since the grids expose only the business name.
    """
    process_number: str
    dictamen_sequence: int = 1
    provider_cuit: str                              # resolved; rows without a match are dropped
    provider_name: Optional[str] = None
    group: Optional[str] = None
    line_number: Optional[int] = None
    alternative_number: Optional[int] = None
    merit_order: Optional[int] = None               # secondary-offers grid only
    is_primary: Optional[bool] = None
    quantity: Optional[float] = None
    unit_of_measure: Optional[str] = None
    unit_price: Optional[float] = None
    total_per_line: Optional[float] = None
    currency: Optional[str] = None


class RejectedRelProps(BaseModel):
    """One REJECTED relationship: Dictamen -> Provider.

    Carries the evaluation committee's per-requirement rejection reasons (one
    string per discarded-evaluation grid row, tagged with the failing area) and
    the free-text justification. The rejected-bidder block exposes the CUIT
    directly.
    """
    process_number: str
    dictamen_sequence: int = 1
    provider_cuit: str
    provider_name: Optional[str] = None
    reasons: List[str] = Field(default_factory=list)
    justification: Optional[str] = None


# Aggregated result for one process

class ProcessResult(BaseModel):
    """Everything scraped for a single process number.

    Passed from the orchestrator to the ingestion layer.
    """
    process: ProcessModel
    organization: Optional[OrganizationModel] = None
    contracting_unit: Optional[ContractingUnitModel] = None
    line_items: List[LineItemModel] = Field(default_factory=list)
    procurement_requests: List[ProcurementRequestModel] = Field(default_factory=list)
    penalties: List[PenaltyModel] = Field(default_factory=list)
    gde_documents: List[GDEDocumentModel] = Field(default_factory=list)
    invites: List[InvitesRelProps] = Field(default_factory=list)
    providers: List[ProviderModel] = Field(default_factory=list)
    bids: List[BidModel] = Field(default_factory=list)
    bid_lines: List[BidLineModel] = Field(default_factory=list)
    contractual_documents: List[ContractualDocumentModel] = Field(default_factory=list)
    contract_lines: List[ContractLineModel] = Field(default_factory=list)
    authorizations_cd: List[tuple[str, AuthorizedByRelProps]] = Field(
        default_factory=list,
        description="(document_number, rel_props) for ContractualDocument->Authorizer"
    )
    authorizers: List[AuthorizerModel] = Field(default_factory=list)
    provision_requests: List[ProvisionRequestModel] = Field(default_factory=list)
    provision_request_lines: List[ProvisionRequestLineModel] = Field(default_factory=list)
    authorizations_spr: List[tuple[str, AuthorizedByRelProps]] = Field(
        default_factory=list,
        description="(request_number, rel_props) for ProvisionRequest->Authorizer"
    )
    dictamenes: List[DictamenModel] = Field(
        default_factory=list,
        description="Pre-award opinions: Process->Dictamen HAS_DICTAMEN (CONTRAT.AR)"
    )
    dictamen_signers: List[DictamenSignerModel] = Field(
        default_factory=list,
        description="Dictamen committee members keyed by portal username (CONTRAT.AR)"
    )
    evaluations: List[EvaluatedByRelProps] = Field(
        default_factory=list,
        description="Dictamen signers: Dictamen->DictamenSigner EVALUATED_BY rels (CONTRAT.AR)"
    )
    pre_adjudications: List[PreAdjudicatesRelProps] = Field(
        default_factory=list,
        description="Pre-award recommendations: Dictamen->Provider PRE_ADJUDICATES (CONTRAT.AR)"
    )
    rejections: List[RejectedRelProps] = Field(
        default_factory=list,
        description="Discarded bidders: Dictamen->Provider REJECTED (CONTRAT.AR)"
    )
