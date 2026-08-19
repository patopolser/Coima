"""
date_filter.py — Optional run-scoped date window for the detector.

A detection run may be restricted to a date range. When set, every check limits
the Process population it evaluates to processes whose `opening_date` falls inside
the window. The window travels through the effective config under the `date_range`
key ({"from": "YYYY-MM-DD" | None, "to": "YYYY-MM-DD" | None}) and surfaces in
queries as the $date_from / $date_to parameters.

Semantics (product decision):
  * A null bound leaves that side open (no restriction).
  * When either bound is set, processes WITHOUT an opening_date are EXCLUDED, so a
    windowed run only ever considers dated processes.

Keep the WHERE fragment and the params builder here so the rule stays in one place;
checks reference `$date_from`/`$date_to` and call process_date_filter(alias) when
building their Cypher.
"""

from __future__ import annotations


# Always-present binding so queries can reference $date_from/$date_to even when no
# window is active (Neo4j requires every referenced parameter to be supplied).
NO_WINDOW = {"date_from": None, "date_to": None}


def date_params(cfg: dict | None) -> dict:
    """Extract {date_from, date_to} from the effective config for query binding."""
    dr = (cfg or {}).get("date_range") or {}
    return {"date_from": dr.get("from"), "date_to": dr.get("to")}


def is_windowed(cfg: dict | None) -> bool:
    """True when the effective config carries at least one date bound."""
    p = date_params(cfg)
    return bool(p["date_from"] or p["date_to"])


def process_date_filter(alias: str = "proc") -> str:
    """
    Null-safe Cypher WHERE fragment restricting `alias` (a Process) to the window.

    With both bounds null the fragment is always true (no active window). When a
    bound is set, the Process must carry a non-null opening_date inside it, so
    date-less processes drop out of a windowed run.
    """
    return (
        f"($date_from IS NULL OR ({alias}.opening_date IS NOT NULL "
        f"AND date({alias}.opening_date) >= date($date_from))) "
        f"AND ($date_to IS NULL OR ({alias}.opening_date IS NOT NULL "
        f"AND date({alias}.opening_date) <= date($date_to)))"
    )
