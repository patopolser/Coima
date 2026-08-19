"""
price_entities.py - Shared metadata for the price-bearing entities linked to
economic indicators.

The ingestion-time relationship builder (`ingestion.economic_indicators`)
uses this per-kind metadata to build its MATCH patterns, removing the
near-identical six-way duplication that previously lived inline.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PriceEntitySpec:
    """Describes a price-bearing node kind for economic-indicator linking.

    Attributes:
        kind: Internal key (e.g. ``"bid"``).
        label: Neo4j node label (e.g. ``"Bid"``).
        match_keys: Property names that uniquely identify the node, used to
            build ``MATCH`` patterns.
        total_field: Property holding the line/total amount, or None.
        unit_field: Property holding the unit price, or None.
        amount_fields: All amount-bearing property names, stored on the
            relationship as metadata.
    """

    kind: str
    label: str
    match_keys: tuple[str, ...]
    total_field: str | None
    unit_field: str | None
    amount_fields: tuple[str, ...]

    def node_match(self, alias: str = "n", row: str = "row") -> str:
        """Return a ``MATCH`` clause binding the node from a batch ``row``.

        Args:
            alias: Variable name to bind the node to.
            row: Name of the UNWIND row variable holding the key values.

        Returns:
            A Cypher ``MATCH`` clause string.
        """
        props = ", ".join(f"{key}: {row}.{key}" for key in self.match_keys)
        return f"MATCH ({alias}:{self.label} {{{props}}})"


PRICE_ENTITIES: tuple[PriceEntitySpec, ...] = (
    PriceEntitySpec(
        kind="bid",
        label="Bid",
        match_keys=("process_number", "provider_cuit"),
        total_field="total_amount",
        unit_field=None,
        amount_fields=("total_amount",),
    ),
    PriceEntitySpec(
        kind="bid_line",
        label="BidLine",
        match_keys=("process_number", "provider_cuit", "line_number", "alternative_number"),
        total_field="total_per_line",
        unit_field="unit_price",
        amount_fields=("unit_price", "total_per_line"),
    ),
    PriceEntitySpec(
        kind="contractual_document",
        label="ContractualDocument",
        match_keys=("document_number", "source"),
        total_field="total_amount",
        unit_field=None,
        amount_fields=("total_amount", "max_extendable_amount", "available_extension_amount"),
    ),
    PriceEntitySpec(
        kind="contract_line",
        label="ContractLine",
        match_keys=("document_number", "source", "line_number", "alternative_number"),
        total_field="total_price",
        unit_field="unit_price",
        amount_fields=("unit_price", "total_price"),
    ),
    PriceEntitySpec(
        kind="provision_request",
        label="ProvisionRequest",
        match_keys=("request_number",),
        total_field="total_amount",
        unit_field=None,
        amount_fields=("total_amount",),
    ),
    PriceEntitySpec(
        kind="provision_request_line",
        label="ProvisionRequestLine",
        match_keys=("request_number", "line_number", "alternative_number"),
        total_field="total_price",
        unit_field="unit_price",
        amount_fields=("unit_price", "total_price"),
    ),
)

PRICE_ENTITIES_BY_KIND: dict[str, PriceEntitySpec] = {spec.kind: spec for spec in PRICE_ENTITIES}
