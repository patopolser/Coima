"""
src/mcp_server/prompts.py - Server instructions and reusable investigation
prompts (shown as /mcp__coima__<name> slash commands in Claude Code).
"""

from __future__ import annotations

from mcp.server import MCPServer

INSTRUCTIONS = """Coima exposes Argentine federal public-procurement data (COMPR.AR / CONTRAT.AR) and the
red flags its detectors found, to investigate possible corruption and bid rigging.

Where the data lives:
- Detection results (risk scores, findings per check) come from the latest finished detection run.
  Start with get_detection_status; list_checks explains every red-flag check.
- The raw procurement graph (processes, bids, purchase orders, officials, contacts) is in Neo4j:
  search_tenders / get_tender / get_entity_graph, and run_cypher for anything else
  (read get_graph_schema first).
- Investigation cases persist across sessions: list_investigations / get_investigation to resume,
  create_investigation, add_subject, add_note, save_report to record work.

Suggested workflow: find the entity (search_providers, search_entities, search_tenders) ->
get_entity_profile and get_entity_risk_breakdown -> get_network_neighborhood and
list_related_companies to map the network -> get_tender on the key processes -> record findings
with add_note as you go and finish with save_report.

When analyzing, consider:
- Behaviour patterns: single bidder, serial winner, cover bidding, bid rotation.
- Cartel / collusion networks: groups that repeatedly co-bid and rotate wins (bid_rotation_ring),
  providers linked by shared contacts that also bid together (shared_contact_cluster), dense
  co-bidding communities (cobid_community) and authorizer-unit-provider triads
  (authorizer_provider_ring).
- Risk scoring: a score combines weighted findings with a log-intensity term, multiplied by a
  SYNERGY factor when corroborating patterns co-occur (matched syndromes), with a CONFIDENCE count
  of independent evidence vectors. get_entity_risk_breakdown shows the per-check contributions.
- Connections between providers via shared phone / email / address.
- Temporal patterns (voided processes followed by direct contracts, spending spikes).
- Concentration of awards in specific contracting units or signing officials.

Be rigorous: cite CUITs, process numbers, amounts and dates; separate what the data shows from what
it merely suggests; a red flag is a lead, not proof of wrongdoing. Reply in the user's language."""


REPORT_PROMPTS = {
    "executive_summary": """Create a structured one-page executive summary with:

1. **Overview**: the investigation subjects and scope
2. **Key Findings**: the most significant red flags and patterns detected
3. **Risk Assessment**: overall risk level (High/Medium/Low) with justification
4. **Evidence Summary**: specific tenders, patterns, amounts
5. **Recommendations**: next steps for investigators

Use clear, professional language suitable for government auditors. Be specific with numbers and dates.""",

    "timeline": """Create a chronological timeline showing:

1. All relevant events in order (tender openings, awards, voids)
2. The pattern of behaviour over time (rising win rates, emerging partnerships)
3. Key dates when suspicious patterns began or intensified
4. Gaps or anomalies in the timeline

Mark dates clearly and group events by year/month where it helps.""",

    "network_analysis": """Map out:

1. **Central Actors**: the main companies/individuals under investigation
2. **Connected Entities**: other companies that appear in patterns with the subjects
3. **Relationship Types**: how they are connected (rotation partners, shared tenders, shared contacts, same units/officials)
4. **Strength of Connections**: frequency and consistency of the patterns
5. **Risk Propagation**: which connections suggest coordinated behaviour

Include a textual description of the network that could be visualized.""",

    "cartel_hypothesis": """State, test and rate concrete hypotheses that the subjects form (or belong to) a bid-rigging
cartel. Work from the detected network signals, not assumptions: for each subject company call
get_network_neighborhood and get_entity_risk_breakdown, and pull in the co-members they reveal.

Then write:

1. **Candidate cartels**: each suspected group, its members (CUIT + name) and how they are linked.
2. **Hypotheses**: a falsifiable statement per group (e.g. "X, Y, Z rotate wins in unit U, coordinated via shared phone P").
3. **Supporting evidence**: findings, rotation %, shared processes, synergies, centrality; cite process numbers, amounts and dates.
4. **Counter-evidence / gaps**: what would disprove it and what data is missing.
5. **Confidence rating**: High / Medium / Low per hypothesis, grounded in the number of independent corroborating vectors.
6. **Recommended next steps**: targeted queries, companies to add, external lookups.

Do not overstate: separate what the data shows from what it merely suggests.""",
}


def _report_prompt(report_type: str, body: str):
    def prompt(investigation_id: str) -> str:
        return (
            f"Write a {report_type.replace('_', ' ')} report for Coima investigation {investigation_id}.\n\n"
            f"First call get_investigation('{investigation_id}') to load its subjects, notes and earlier "
            "reports, then gather whatever evidence is missing with the Coima tools.\n\n"
            f"{body}\n\n"
            "Format the report in Markdown, show it to me, and store it with "
            f"save_report(investigation_id='{investigation_id}', report_type='{report_type}', content=...)."
        )
    return prompt


def register(mcp: MCPServer) -> None:
    @mcp.prompt(title="Investigate a company")
    def investigate_company(cuit: str) -> str:
        """Open (or resume) a case on a provider and investigate it end to end."""
        return (
            f"Investigate the provider with CUIT {cuit} using the Coima tools.\n\n"
            f"1. list_investigations(search='{cuit}'): resume an existing case with get_investigation, "
            f"or create_investigation with this company as subject.\n"
            "2. get_entity_profile and get_entity_risk_breakdown for the company.\n"
            "3. get_network_neighborhood and list_related_companies; add the strongest co-members as subjects.\n"
            "4. search_tenders(cuit=...) and get_tender on the processes the findings point to.\n"
            "5. Record each substantive finding with add_note as you go (cite CUITs, process numbers, amounts, dates).\n\n"
            "End with a short assessment: risk level, the evidence behind it, and open questions."
        )

    for report_type, body in REPORT_PROMPTS.items():
        mcp.prompt(
            name=f"report_{report_type}",
            title=f"Report: {report_type.replace('_', ' ')}",
            description=f"Write and save a {report_type.replace('_', ' ')} report for an investigation case.",
        )(_report_prompt(report_type, body))
