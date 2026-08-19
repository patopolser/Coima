"""
src/detector/columns.py - Typed column descriptor factories for check `ui_meta`.

Each factory returns a dict that the frontend uses to render one column of a
check's result table. The dict carries two things: a `type` that selects the
renderer (see CheckDetail.jsx) and one or more `*_key` fields that point at the
row keys whose values feed that renderer. Splitting the primary key from
sibling keys (urls, names, currency) lets a check expose extra fields without
the frontend having to guess their names.

Usage inside a CHECK's ui_meta:
    from src.detector.columns import col_process, col_provider, col_percentage

    "columns": [
        col_process("process", "Process", url_key="process_url"),
        col_provider("provider_cuit", "Provider", name_key="company", url_key="coima_url"),
        col_percentage("round_pct", "Round %"),
    ]
"""

from __future__ import annotations
from typing import Optional


def col_process(key: str, label: str, *, url_key: Optional[str] = None) -> dict:
    """
    A single procurement process. Rendered as a clickable process number that
    links to comprar.gob.ar.

    key:     row field holding the process_number string
    url_key: row field holding the external URL (optional)
    """
    return {"type": "Process", "key": key, "label": label, "url_key": url_key}


def col_provider(key: str, label: str, *, name_key: Optional[str] = None, url_key: Optional[str] = None) -> dict:
    """
    A single provider (empresa). Rendered as the CUIT linked to /companies/<cuit>
    with the business name alongside.

    key:      row field holding the CUIT (primary identifier)
    name_key: row field holding the business name
    url_key:  row field holding the Coima profile URL (optional)
    """
    return {"type": "Provider", "key": key, "label": label, "name_key": name_key, "url_key": url_key}


def col_quantity(key: str, label: str) -> dict:
    """An integer count rendered as a plain number."""
    return {"type": "Quantity", "key": key, "label": label}


def col_percentage(key: str, label: str) -> dict:
    """A numeric percentage in [0, 100] rendered as '<value>%'."""
    return {"type": "Percentage", "key": key, "label": label}


def col_string(key: str, label: str) -> dict:
    """A plain text value."""
    return {"type": "String", "key": key, "label": label}


def col_money(key: str, label: str, *, currency_key: Optional[str] = None) -> dict:
    """
    A single monetary amount rendered as '<currency> <amount>', or just the
    amount when no currency is available.

    key:          row field holding the numeric amount
    currency_key: row field holding the ISO currency code (e.g. 'ARS')
    """
    return {"type": "Money", "key": key, "label": label, "currency_key": currency_key}


def col_date(key: str, label: str) -> dict:
    """An ISO date string rendered in the user's locale format."""
    return {"type": "Date", "key": key, "label": label}


def col_unit(key: str, label: str, *, name_key: Optional[str] = None) -> dict:
    """
    A contracting unit (UOC/SAF). Rendered as the code linked to /units/<code>
    with the unit name alongside.

    key:      row field holding the unit SAF/UOC code
    name_key: row field holding the unit name
    """
    return {"type": "Unit", "key": key, "label": label, "name_key": name_key}


def col_organization(key: str, label: str, *, name_key: Optional[str] = None) -> dict:
    """
    A government organization (SAF/Organization node). Rendered as saf_code
    plus name.

    key:      row field holding the saf_code
    name_key: row field holding the organization name
    """
    return {"type": "Organization", "key": key, "label": label, "name_key": name_key}


def col_authorizer(key: str, label: str) -> dict:
    """
    A public official who authorizes contracts. Rendered as the name linked to
    /authorizers/<name>. The row value is the authorizer name, which doubles as
    its identifier (authorizers have no separate code).
    """
    return {"type": "Authorizer", "key": key, "label": label}


def col_contact(key: str, label: str) -> dict:
    """
    A single contact point. The row value must be a dict of the form
    {type: 'email'|'phone'|'address', contact: str}.
    """
    return {"type": "Contact", "key": key, "label": label}


# List types expect the row field to be a list of objects.

def col_list_process(key: str, label: str) -> dict:
    """
    A list of processes rendered as comma-separated clickable process numbers.
    Row value: [{process_number: str, comprar_url: str|None}, ...]
    """
    return {"type": "ListProcess", "key": key, "label": label}


def col_list_string(key: str, label: str) -> dict:
    """
    A list of text values rendered comma-separated.
    Row value: [{text: str}, ...] or [str, ...]
    """
    return {"type": "ListString", "key": key, "label": label}


def col_list_money(key: str, label: str) -> dict:
    """
    A list of monetary amounts, one per currency, rendered as
    'ARS 1,234,567 / USD 500'.
    Row value: [{currency: str, amount: float}, ...]
    """
    return {"type": "ListMoney", "key": key, "label": label}


def col_list_unit(key: str, label: str) -> dict:
    """
    A list of contracting units.
    Row value: [{code: str, name: str}, ...]
    """
    return {"type": "ListUnit", "key": key, "label": label}


def col_list_organization(key: str, label: str) -> dict:
    """
    A list of organizations.
    Row value: [{saf_code: str, name: str}, ...]
    """
    return {"type": "ListOrganization", "key": key, "label": label}


def col_list_contact(key: str, label: str) -> dict:
    """
    A list of contact points rendered as 'email: a@b.com, phone: 555-1234'.
    Row value: [{type: str, contact: str}, ...]
    """
    return {"type": "ListContact", "key": key, "label": label}
