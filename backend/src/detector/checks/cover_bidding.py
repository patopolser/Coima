"""
cover_bidding.py — Awarded competitive processes where the runner-up offer sits
suspiciously close to the winning offer.

In a genuine competition, the gap between the cheapest (winning) bid and the next
cheapest is unpredictable. When several bidders compete yet the runner-up lands
within a razor-thin margin above the winner, the losing offers look like
complementary "cover" bids designed to lose narrowly and simulate competition.

Offers are compared as registered (raw amount), restricted to bids in the same
currency as the winning bid so the ranking is apples-to-apples, and shown in their
original currency. Both the winner and the narrowly-beaten runner-up are scored,
since cover bidding implicates both sides. One row per (process, winner).
"""

from src.detector.columns import col_process, col_provider, col_quantity, col_money, col_percentage

QUERY = """
// Winning bid in an awarded process
MATCH (proc:Process)-[:HAS_BID]->(wbid:Bid)-[:SUBMITTED_BY]->(winner:Provider)
MATCH (proc)-[:GENERATES]->(:ContractualDocument)-[:AWARDED_TO]->(winner)
WHERE wbid.total_amount IS NOT NULL AND wbid.total_amount > 0
  AND ($date_from IS NULL OR (proc.opening_date IS NOT NULL AND date(proc.opening_date) >= date($date_from)))
  AND ($date_to   IS NULL OR (proc.opening_date IS NOT NULL AND date(proc.opening_date) <= date($date_to)))
WITH proc, winner,
     wbid.total_amount        AS won_amount,
     coalesce(wbid.currency, 'ARS') AS currency

// Every other competing bid registered in the same currency as the winner
MATCH (proc)-[:HAS_BID]->(obid:Bid)-[:SUBMITTED_BY]->(other:Provider)
WHERE other <> winner
  AND obid.total_amount IS NOT NULL AND obid.total_amount > 0
  AND coalesce(obid.currency, 'ARS') = currency
WITH proc, winner, won_amount, currency,
     collect({
        amount: obid.total_amount,
        cuit:   other.cuit,
        name:   coalesce(other.business_name, '—')
     }) AS others
WHERE size(others) >= $min_competitors

// Runner-up = cheapest competing bid
WITH proc, winner, won_amount, currency, others,
     reduce(best = null, o IN others |
        CASE WHEN best IS NULL OR o.amount < best.amount THEN o ELSE best END) AS runner

// Winner is the cheapest, runner-up sits razor-thin above
WHERE runner.amount >= won_amount
  AND runner.amount <= won_amount * (1 + $max_margin_pct / 100.0)

RETURN
    proc.process_number                    AS process_number,
    proc.source_url                        AS process_url,
    winner.cuit                            AS provider_cuit,
    coalesce(winner.business_name, '—')   AS provider_name,
    size(others)                           AS competing_bids,
    won_amount,
    runner.amount                          AS runner_up_amount,
    runner.cuit                            AS runner_up_cuit,
    runner.name                            AS runner_up_name,
    currency,
    round(100.0 * (runner.amount - won_amount) / won_amount, 2) AS margin_pct
ORDER BY margin_pct ASC, competing_bids DESC
LIMIT $limit
"""

THRESHOLDS = {
    "cover_min_competitors": 2,
    "cover_max_margin_pct":  2.0,
}

CHECK = {
    "key":    "cover_bidding",
    "label":  "Cover Bidding",
    "weight": 20,
    "thresholds": THRESHOLDS,
    "query":  QUERY,
    "params": lambda cfg, limit: {
        "limit":           limit,
        "min_competitors": cfg.get("thresholds", {}).get("cover_min_competitors", THRESHOLDS["cover_min_competitors"]),
        "max_margin_pct":  cfg.get("thresholds", {}).get("cover_max_margin_pct",  THRESHOLDS["cover_max_margin_pct"]),
    },
    "score_extractors": [
        lambda r: (r.get("provider_cuit"), r.get("provider_name")),
        lambda r: (r.get("runner_up_cuit"), r.get("runner_up_name")),
    ],
    "report_headers": ["Process", "Winner", "Company", "Runner-up", "Runner-up Co.", "Rivals", "Won", "Runner-up", "Margin %"],
    "report_row": lambda r: [
        r["process_number"], r["provider_cuit"], r["provider_name"][:20],
        r["runner_up_cuit"], r["runner_up_name"][:20],
        r["competing_bids"],
        f"{r['currency']} {r['won_amount']:,.0f}",
        f"{r['currency']} {r['runner_up_amount']:,.0f}",
        f"{r['margin_pct']}%",
    ],
    "report_title": "COVER BIDDING — Runner-up razor-thin above the winner in a contested process",
    "ui_meta": {
        "description": (
            "Flags awarded processes with several bidders where the runner-up offer sits within "
            "a razor-thin margin above the winning offer (compared on the registered prices). "
            "Losing bids clustered just above the winner suggest complementary 'cover' bids that "
            "simulate competition."
        ),
        "color": "indigo",
        "columns": [
            col_process("process_number",     "Process",     url_key="process_url"),
            col_provider("provider_cuit",      "Winner",      name_key="provider_name"),
            col_provider("runner_up_cuit",     "Runner-up",   name_key="runner_up_name"),
            col_quantity("competing_bids",     "Rivals"),
            col_money("won_amount",             "Won",         currency_key="currency"),
            col_money("runner_up_amount",       "Runner-up Bid", currency_key="currency"),
            col_percentage("margin_pct",        "Margin %"),
        ],
        "search_fields": ["process_number", "provider_cuit", "provider_name", "runner_up_cuit", "runner_up_name"],
    },
    "i18n": {
        "es": {
            "label": "Ofertas de Cobertura",
            "description": (
                "Marca procesos adjudicados con varios oferentes donde la segunda oferta más "
                "barata queda a un margen mínimo por encima de la ganadora (comparadas sobre los "
                "precios registrados). Ofertas perdedoras pegadas a la ganadora sugieren ofertas "
                "de cobertura que simulan competencia."
            ),
            "columns": {
                "process_number":   "Proceso",
                "provider_cuit":    "Ganador",
                "runner_up_cuit":   "Segundo",
                "competing_bids":   "Rivales",
                "won_amount":       "Ganada",
                "runner_up_amount": "Oferta Segundo",
                "margin_pct":       "% Margen",
            },
        },
    },
}
