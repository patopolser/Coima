"""
parsers.py - Shared parsing helpers for date, number, string, URL and
process-number values.

Centralised here so the scraper page modules avoid duplication and site-specific
formatting quirks can be adjusted in one place.
"""

from __future__ import annotations

import re
from datetime import date, datetime

_NULLISH_TEXT_VALUES = {
    "no definido",
    "no definida",
    "no informada",
    "no informado",
    "no aplica",
    "no disponible",
    "sin definir",
    "sin dato",
    "s/d",
    "n/d",
    "n/a",
    "na",
    "none",
    "null",
    "-",
    "--",
}


def is_nullish_text(value: str | None) -> bool:
    """Return True when a text value is a semantic null placeholder.

    Args:
        value: Raw text to inspect.

    Returns:
        True if the value is None or a known placeholder (e.g. "s/d", "n/a").
    """
    if value is None:
        return True
    collapsed = re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip().lower()
    return collapsed in _NULLISH_TEXT_VALUES


def clean_text(value: str | None) -> str | None:
    """Collapse whitespace and discard semantic-null placeholders.

    Strips leading/trailing whitespace and collapses internal runs of
    whitespace (including non-breaking spaces) to a single space.

    Args:
        value: Raw text to clean.

    Returns:
        The cleaned string, or None if it is empty or a null placeholder.
    """
    if value is None:
        return None
    cleaned = value.replace("\xa0", " ").replace("&nbsp;", " ").replace("&nbsp", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if is_nullish_text(cleaned):
        return None
    return cleaned or None


def clean_cuit(cuit_str: str | None) -> str | None:
    """Remove hyphens and non-digit characters from a CUIT string."""
    if not cuit_str:
        return None
    cleaned = re.sub(r"[^\d]", "", cuit_str)
    return cleaned if cleaned else None


def normalize_name(value: str | None) -> str | None:
    """Upper-case and clean a name string (used for Authorizer.full_name)."""
    if value is None:
        return None
    return clean_text(value.upper())


def normalize_currency(value: str | None) -> str | None:
    """Normalize currency labels to standard short codes (e.g. ARS, USD).

    Args:
        value: Raw currency label as shown on the portal.

    Returns:
        A short code (ARS, USD, EUR, GBP, BRL, CHF, JPY) when recognised;
        otherwise the cleaned original text, or None if empty.
    """
    text = clean_text(value)
    if not text:
        return None

    upper = (
        text.upper()
        .replace("Á", "A")
        .replace("É", "E")
        .replace("Í", "I")
        .replace("Ó", "O")
        .replace("Ú", "U")
    )

    if "ARS" in upper or "PESO ARGENTINO" in upper or upper.strip() == "$":
        return "ARS"
    if "USD" in upper or "DOLAR ESTADOUNIDENSE" in upper or "US$" in upper:
        return "USD"
    if "EUR" in upper or "EURO - EUROPEAN MONETARY UNION" in upper:
        return "EUR"
    if "GBP" in upper or "LIBRA ESTERLINA" in upper:
        return "GBP"
    if "BRL" in upper or "REAL" in upper:
        return "BRL"
    if "CHF" in upper or "FRANCO SUIZO" in upper:
        return "CHF"
    if "JPY" in upper or "YEN JAPONES" in upper:
        return "JPY"

    return text


def parse_float(value: str | None) -> float | None:
    """Parse an Argentine-formatted float string to a Python float.

    Examples:
        "63.000,00"    -> 63000.0
        "1.350.000,00" -> 1350000.0
        "5,0"          -> 5.0
        ""             -> None
    """
    if not value:
        return None
    # Remove thousands separator (.) and replace decimal comma with dot.
    cleaned = re.sub(r"\.", "", value.strip()).replace(",", ".")
    # Strip any trailing non-numeric chars except dot.
    cleaned = re.sub(r"[^\d.]", "", cleaned)
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_int(value: str | None) -> int | None:
    """Parse an integer string, stripping formatting characters."""
    if not value:
        return None
    cleaned = re.sub(r"[^\d]", "", value.strip())
    try:
        return int(cleaned)
    except ValueError:
        return None


def parse_bool(value: str | None) -> bool | None:
    """Map Spanish/English yes-no strings to a bool, or None if unrecognised."""
    if value is None:
        return None
    lower = value.strip().lower()
    if lower in {"si", "sí", "yes", "true", "1", "x"}:
        return True
    if lower in {"no", "false", "0", ""}:
        return False
    return None


# Formats encountered on comprar.gob.ar pages. Order matters: try the most
# specific format first.
_DATETIME_FORMATS = [
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y %I:%M:%S %p",
    "%d/%m/%Y %I:%M %p",
    "%d/%m/%Y %H:%M Hrs.",
    "%d/%m/%Y %H:%M Hrs",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
]

_DATE_FORMATS = [
    "%d/%m/%Y",
    "%Y-%m-%d",
]


def parse_datetime(value: str | None) -> datetime | None:
    """Parse a datetime string using the formats seen on comprar.gob.ar."""
    if not value:
        return None
    text = clean_text(value) or ""

    # Normalize COMPR.AR variants like "03:07:03 p.m." / "a.m.".
    normalized = re.sub(r"(?i)a\s*\.\s*m\s*\.", "AM", text)
    normalized = re.sub(r"(?i)p\s*\.\s*m\s*\.", "PM", normalized)
    normalized = re.sub(r"\bam\b", "AM", normalized, flags=re.I)
    normalized = re.sub(r"\bpm\b", "PM", normalized, flags=re.I)

    candidates = [text]
    if normalized != text:
        candidates.append(normalized)

    for candidate in candidates:
        for fmt in _DATETIME_FORMATS:
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                continue
    return None


def parse_date(value: str | None) -> date | None:
    """Parse a date-only string, falling back to datetime parsing."""
    if not value:
        return None
    text = clean_text(value) or ""
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    dt = parse_datetime(text)
    return dt.date() if dt else None


def extract_qs_token(url: str | None) -> str | None:
    """Extract the `qs` query-parameter value from a comprar.gob.ar URL."""
    if not url:
        return None
    match = re.search(r"[?&]qs=([^&]+)", url, re.IGNORECASE)
    return match.group(1) if match else None


def make_absolute(base_url: str, relative: str | None) -> str | None:
    """Resolve a relative path against the base URL."""
    if not relative:
        return None
    if relative.startswith("http"):
        return relative
    return base_url.rstrip("/") + "/" + relative.lstrip("/")


_PROCESS_NUMBER_RE = re.compile(
    r"^(?P<saf_code>[\d/]+)-(?P<sequence>\d+)-(?P<type_code>[A-Z]+)(?P<year>\d{2})$"
)


def parse_process_number(process_number: str) -> dict[str, str]:
    """Decompose a process number string into its components.

    Args:
        process_number: e.g. "96-0043-LPR21", "14/3-0093-LPR24".

    Returns:
        A dict with keys saf_code, sequence, type_code, year (all raw
        strings), or an empty dict if the input does not match.
    """
    m = _PROCESS_NUMBER_RE.match(process_number.strip())
    if not m:
        return {}
    return m.groupdict()


def extract_saf_code(process_number: str) -> int | None:
    """Return the numeric SAF code from a process number (e.g. "14/3" -> 14)."""
    parts = parse_process_number(process_number)
    if not parts:
        return None
    try:
        return int(parts["saf_code"].split("/")[0])
    except (ValueError, IndexError):
        return None


# The UOC field is nominally "<code> - <name>", but on the portal the code is
# sometimes joined to the name by a plain space or a dash with no surrounding
# whitespace, and the literal " - " separator can also appear inside the name
# (e.g. "... / Argentina - Portugal (MOU)"). Anchoring on the leading code
# token instead of splitting on " - " avoids cutting in the wrong place.
#
# A code token is a run of digit groups joined by "/" or "-" (e.g. "262/11",
# "101-000", "14/3", "142/000", "14/3-000"). At least one separator is
# required so a name that merely starts with a number is not mistaken for a
# code.
_UOC_CODE_RE = re.compile(
    r"^\s*(?P<code>\d+(?:[/-]\d+)+)\s*[-–—]?\s*(?P<name>.*)$",
    re.DOTALL,
)


def split_uoc(raw: str | None) -> tuple[str | None, str | None]:
    """Split a raw UOC field into (code, name).

    Falls back to a " - " split when no code token is detected, and finally to
    treating the whole string as the code.
    """
    if not raw:
        return None, None
    m = _UOC_CODE_RE.match(raw)
    if m:
        return clean_text(m.group("code")), clean_text(m.group("name"))
    if " - " in raw:
        code, name = raw.split(" - ", 1)
        return clean_text(code), clean_text(name)
    return clean_text(raw), None
