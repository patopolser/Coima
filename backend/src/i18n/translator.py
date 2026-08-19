"""
src/i18n/translator.py - Load locale JSON catalogs and translate API strings.

Catalogs are lazy-loaded once and cached in `_catalogs`. Lookup falls back to
the English catalog when a key is missing in the requested locale, then to
the supplied default string.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

_LOCALES_DIR = Path(__file__).parent / "locales"
_SUPPORTED = frozenset({"en", "es"})
_catalogs: Dict[str, dict] = {}


def _load_catalogs() -> None:
    if _catalogs:
        return
    for locale in _SUPPORTED:
        path = _LOCALES_DIR / f"{locale}.json"
        with open(path, encoding="utf-8") as f:
            _catalogs[locale] = json.load(f)


def normalize_locale(value: str | None) -> str:
    """Reduce an Accept-Language or `?lang=` value to one of the supported locales."""
    if not value:
        return "en"
    primary = value.split(",")[0].strip().split(";")[0].strip().lower()
    if primary.startswith("es"):
        return "es"
    return "en"


def _get_nested(data: dict, key: str) -> str | None:
    node: Any = data
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, str) else None


def t(key: str, locale: str = "en", default: str = "", **kwargs: Any) -> str:
    """Look up `key` in the locale catalog, with English and `default` as fallbacks."""
    _load_catalogs()
    loc = normalize_locale(locale)
    text = _get_nested(_catalogs.get(loc, {}), key)
    if text is None and loc != "en":
        text = _get_nested(_catalogs.get("en", {}), key)
    if text is None:
        text = default
    if kwargs and text:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text


def ai_language_instruction(locale: str) -> str:
    """Localized one-liner appended to AI system prompts so the model replies in the user's language."""
    loc = normalize_locale(locale)
    key = "language_instruction_es" if loc == "es" else "language_instruction_en"
    return t(f"ai.{key}", loc, default="Respond in English." if loc == "en" else "Responde en español.")
