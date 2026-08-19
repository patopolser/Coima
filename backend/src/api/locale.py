"""
src/api/locale.py - Resolve the request locale from a query param or the
Accept-Language header.
"""

from __future__ import annotations

from fastapi import Header, Query

from src.i18n.translator import normalize_locale

SUPPORTED_LOCALES = frozenset({"en", "es"})


def get_locale(
    lang: str | None = Query(None, alias="lang"),
    accept_language: str | None = Header(None, alias="Accept-Language"),
) -> str:
    """Pick the response locale, preferring the explicit `?lang=` query parameter."""
    if lang:
        return normalize_locale(lang)
    if accept_language:
        return normalize_locale(accept_language)
    return "en"
