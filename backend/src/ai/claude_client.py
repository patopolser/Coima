"""
src/ai/claude_client.py - Anthropic API client with tool use for corruption
investigation analysis.

Defines the shared TOOLS catalog, REPORT_PROMPTS and ANALYSIS_GUIDANCE used by
every AI backend (Claude, Gemini, DeepSeek), plus the ClaudeClient that drives
the Anthropic API and the CoimaTools implementations that resolve each tool
call against the detection data and Neo4j.
"""

import os
import json
import re
from typing import Generator, Optional
from datetime import datetime

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

try:
    from neo4j import GraphDatabase
    HAS_NEO4J = True
except ImportError:
    HAS_NEO4J = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


TOOLS = [
    {
        "name": "get_company_data",
        "description": "Get all data about a company from the corruption detection system, including risk score, flags, and all findings where this company appears. Use this to understand a company's involvement in suspicious patterns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cuit": {
                    "type": "string",
                    "description": "The CUIT (tax ID) of the company to look up"
                }
            },
            "required": ["cuit"]
        }
    },
    {
        "name": "get_tender_data",
        "description": "Get detailed information about a specific tender/licitación, including bidders, winner, and any flags. Use this to analyze a specific procurement process.",
        "input_schema": {
            "type": "object",
            "properties": {
                "process": {
                    "type": "string",
                    "description": "The process number of the tender (e.g., '84/13-2056-LPR24')"
                }
            },
            "required": ["process"]
        }
    },
    {
        "name": "query_neo4j",
        "description": "Execute a read-only Cypher query against the Neo4j graph database of public procurement data from COMPR.AR Argentina. Nodes: Process (process_number, status, modality, opening_date), Provider (cuit, business_name, address, city, province, phone, email), ContractingUnit (code, name, saf_code), Organization (saf_code, name), Bid (total_amount=TOTAL of all lines for that provider in the process, currency, status — one Bid per provider/process), BidLine (line_number, alternative_number, offered_quantity, unit_price, total_per_line — use this for per-line price analysis between providers), ContractualDocument (document_number, document_type, total_amount, status, process_number), ContractLine, ProvisionRequest, Authorizer, Phone (value), Email (value), Address (value). Relationships: MANAGED_BY (Process→ContractingUnit), BELONGS_TO (ContractingUnit→Organization), HAS_BID (Process→Bid), SUBMITTED_BY (Bid→Provider), HAS_BID_LINE (Bid→BidLine), FOR_LINE_ITEM (BidLine→LineItem), GENERATES (Process→ContractualDocument), AWARDED_TO (ContractualDocument→Provider), HAS_CONTRACT_LINE (ContractualDocument→ContractLine), AUTHORIZED_BY (ContractualDocument/ProvisionRequest→Authorizer), HAS_PHONE/HAS_EMAIL/HAS_ADDRESS (Organization/ContractingUnit/Provider→Phone/Email/Address), INVITES (Process→Provider), HAS_PROVISION_REQUEST (ContractualDocument→ProvisionRequest), FULFILLED_BY (ProvisionRequest→Provider). IMPORTANT: To compare prices between competing providers use BidLine (join on line_number), NOT Bid.total_amount.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cypher": {
                    "type": "string",
                    "description": "A read-only Cypher query. Must not contain MERGE, CREATE, DELETE, SET, or REMOVE."
                }
            },
            "required": ["cypher"]
        }
    },
    {
        "name": "search_web",
        "description": "Search the web for news and information about a company or person. Use this to find external context like news articles, legal issues, or public records.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query, e.g., 'JAEJ SA corrupción argentina' or company name + CUIT"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "lookup_afip",
        "description": "Look up public AFIP (tax authority) data for a company by CUIT. Returns registration status, legal name, activities, and registration date if available.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cuit": {
                    "type": "string",
                    "description": "The CUIT to look up (11 digits, no dashes)"
                }
            },
            "required": ["cuit"]
        }
    },
    {
        "name": "list_related_companies",
        "description": "Find companies that appear together with a given company in bid rotation patterns or the same tenders. Use this to map potential cartel networks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cuit": {
                    "type": "string",
                    "description": "The CUIT of the company to find relations for"
                }
            },
            "required": ["cuit"]
        }
    },
    {
        "name": "get_entity_risk_breakdown",
        "description": "Get the smart-scoring breakdown behind a company's risk score: per-check contribution (weight x finding intensity), matched syndromes (correlated patterns that multiplied the score), the synergy multiplier, the confidence count (number of independent corroborating vectors), and the co-bidding network position. Use this to explain WHY a company scores as it does and which combined patterns drive the risk.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cuit": {
                    "type": "string",
                    "description": "The CUIT of the company to explain"
                }
            },
            "required": ["cuit"]
        }
    },
    {
        "name": "get_network_neighborhood",
        "description": "Map a company's position in the co-bidding/collusion network: the bid-rotation rings it belongs to (members, shared processes, win-rotation %), shared-contact clusters (co-owned providers that also bid together), dense co-bidding communities, authorizer-unit-provider triads, and its co-bidding centrality (degree = number of co-bidding partners, betweenness = broker position bridging groups). Use this to identify cartels and the other companies to investigate alongside this one.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cuit": {
                    "type": "string",
                    "description": "The CUIT of the company whose network to map"
                }
            },
            "required": ["cuit"]
        }
    },
]


# Shared analysis guidance injected into every model's system prompt so
# Claude, Gemini and DeepSeek reason about the same patterns and signals.
ANALYSIS_GUIDANCE = """When analyzing, consider:
- Patterns of behavior (single bidder, always wins, bid rotation)
- Cartel / collusion networks: groups that repeatedly co-bid and rotate wins (bid_rotation_ring), providers linked by shared contacts that also bid together (shared_contact_cluster), dense co-bidding communities (cobid_community), and authorizer-unit-provider triads (authorizer_provider_ring). Use get_network_neighborhood(cuit) to map a company's ring/cluster and its co-bidding centrality.
- Risk scoring: a company's score combines weighted findings with a log-intensity term, multiplied by a SYNERGY factor when corroborating patterns co-occur, alongside a CONFIDENCE count of independent vectors. Use get_entity_risk_breakdown(cuit) to see the per-check contributions, matched syndromes, and network position behind a score.
- Connections between providers via shared contact data (phone/email/address)
- Temporal patterns (voided processes followed by direct contracts)
- Concentration of awards in specific contracting units
- Any external information from web searches"""


REPORT_PROMPTS = {
    "executive_summary": """Generate an executive summary report for this corruption investigation.

Based on the investigation data provided, create a structured 1-page executive summary with:

1. **Overview**: Brief description of the investigation subjects and scope
2. **Key Findings**: The most significant red flags and patterns detected
3. **Risk Assessment**: Overall risk level (High/Medium/Low) with justification
4. **Evidence Summary**: Quick reference to specific tenders, patterns, amounts
5. **Recommendations**: Suggested next steps for investigators

Use clear, professional language suitable for government auditors. Be specific with numbers and dates.
Format the output in Markdown.""",

    "timeline": """Generate a chronological timeline report for this corruption investigation.

Based on the investigation data, create a timeline showing:

1. All relevant events in chronological order (tender openings, awards, voids)
2. Pattern of behavior over time (increasing win rates, emerging partnerships)
3. Key dates when suspicious patterns began or intensified
4. Any gaps or anomalies in the timeline

Format as a Markdown document with dates clearly marked. Group events by year/month when appropriate.""",

    "network_analysis": """Generate a network analysis report for this corruption investigation.

Based on the investigation data, map out:

1. **Central Actors**: The main companies/individuals under investigation
2. **Connected Entities**: Other companies that appear in patterns with the subjects
3. **Relationship Types**: How they're connected (bid rotation partners, shared tenders, same units)
4. **Strength of Connections**: Frequency and consistency of patterns
5. **Risk Propagation**: Which connections suggest coordinated behavior

Format as a Markdown document. Include a textual description of the network that could be visualized.""",

    "cartel_hypothesis": """Generate a cartel hypothesis report for this corruption investigation.

Your goal is to state, test and rate concrete hypotheses that the subjects form (or belong to) a bid-rigging cartel. Work from the detected network signals, not assumptions.

First gather evidence: for each subject company call get_network_neighborhood(cuit) to find its rings, shared-contact clusters, communities and triads, and get_entity_risk_breakdown(cuit) to see which correlated patterns (synergies) drive its score. Pull in the co-members those tools reveal.

Then produce, in Markdown:

1. **Candidate cartels**: each suspected group, its member companies (CUIT + name), and how they are linked (co-bidding, shared contacts, authorizer/unit).
2. **Hypotheses**: for each group, a falsifiable statement (e.g. "Companies X, Y, Z rotate wins in unit U, coordinated via shared phone P").
3. **Supporting evidence**: the specific findings, rotation %, shared processes, synergies and centrality that support each hypothesis. Cite process numbers, amounts and dates.
4. **Counter-evidence / gaps**: what would disprove it and what data is missing.
5. **Confidence rating**: High / Medium / Low per hypothesis, with justification grounded in the number of independent corroborating vectors.
6. **Recommended next steps**: targeted queries, companies to add to the investigation, external lookups.

Be rigorous and specific. Do not overstate: separate what the data shows from what it merely suggests.""",
}


def _flatten_list_item(m):
    """Flatten a UI list cell into a plain string for the AI context.

    Handles {text}, {type, contact} (shared contacts), and raw scalars.
    """
    if not isinstance(m, dict):
        return m
    if "text" in m:
        return m["text"]
    if "type" in m or "contact" in m:
        return f"{m.get('type', '')}:{m.get('contact', '')}"
    return m


class CoimaTools:
    """Tool implementations that access the corruption detection data."""

    def __init__(self, company_index: dict, findings: dict, neo4j_config: dict = None):
        self.company_index = company_index
        self.findings = findings
        self.neo4j_driver = None

        if neo4j_config and HAS_NEO4J:
            try:
                self.neo4j_driver = GraphDatabase.driver(
                    neo4j_config.get("uri", "bolt://localhost:7687"),
                    auth=(
                        neo4j_config.get("user", "neo4j"),
                        neo4j_config.get("password", "password")
                    )
                )
            except Exception as e:
                print(f"Neo4j connection failed: {e}")

    def get_company_data(self, cuit: str) -> dict:
        """Return all data the index has on a company, truncating long lists."""
        data = self.company_index.get(cuit)
        if not data:
            return {"error": f"Company with CUIT {cuit} not found in the system"}

        result = {
            "cuit": cuit,
            "risk_score": data.get("risk_score"),
            "findings": {}
        }

        for check_name, rows in data.get("findings", {}).items():
            result["findings"][check_name] = rows[:100]
            if len(rows) > 100:
                result["findings"][f"{check_name}_total"] = len(rows)

        return result

    def get_tender_data(self, process: str) -> dict:
        """Return every finding that references the given process number."""
        results = []

        for check_name, rows in self.findings.items():
            for row in rows:
                if (row.get("process") == process or
                    row.get("voided_process") == process or
                    row.get("direct_process") == process):
                    results.append({
                        "check_type": check_name,
                        "data": row
                    })

        if not results:
            return {"error": f"Tender {process} not found in findings"}

        return {"process": process, "findings": results}

    def query_neo4j(self, cypher: str) -> dict:
        """Execute a read-only Cypher query against the configured Neo4j driver."""
        # Reject any keyword that would mutate the graph before we even open a
        # session, so a poorly worded model request cannot land a write.
        forbidden = ["MERGE", "CREATE", "DELETE", "SET", "REMOVE", "DROP", "DETACH"]
        cypher_upper = cypher.upper()
        for keyword in forbidden:
            if re.search(rf'\b{keyword}\b', cypher_upper):
                return {"error": f"Query contains forbidden keyword: {keyword}. Only read operations allowed."}

        if not self.neo4j_driver:
            return {"error": "Neo4j connection not available. Set NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD environment variables."}

        try:
            with self.neo4j_driver.session() as session:
                result = session.run(cypher + " LIMIT 100")
                records = [dict(r) for r in result]
                return {"query": cypher, "results": records, "count": len(records)}
        except Exception as e:
            return {"error": f"Query execution failed: {str(e)}"}

    def search_web(self, query: str) -> dict:
        """Search the web using the configured Serper API key."""
        from src.api.config import get_settings
        api_key = get_settings().serper_api_key or os.environ.get("SERPER_API_KEY")

        if not api_key:
            return {"error": "Web search not configured. Set COIMA_SERPER_API_KEY or SERPER_API_KEY."}

        if not HAS_REQUESTS:
            return {"error": "requests library not installed"}

        try:
            response = requests.post(
                "https://google.serper.dev/search",
                headers={
                    "X-API-KEY": api_key,
                    "Content-Type": "application/json"
                },
                json={"q": query, "gl": "ar", "hl": "es", "num": 5},
                timeout=10
            )
            data = response.json()
            results = []
            for item in data.get("organic", [])[:5]:
                results.append({
                    "title": item.get("title"),
                    "snippet": item.get("snippet"),
                    "url": item.get("link")
                })
            return {"query": query, "results": results}

        except Exception as e:
            return {"error": f"Web search failed: {str(e)}"}

    def lookup_afip(self, cuit: str) -> dict:
        """Look up AFIP public data for a CUIT."""
        cuit_clean = re.sub(r'\D', '', cuit)
        if len(cuit_clean) != 11:
            return {"error": f"Invalid CUIT format: {cuit}. Must be 11 digits."}

        if not HAS_REQUESTS:
            return {"error": "requests library not installed"}

        try:
            response = requests.get(
                f"https://afip.tangofactura.com/Rest/GetContribuyenteFull?cuit={cuit_clean}",
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    return {
                        "cuit": cuit_clean,
                        "name": data.get("Contribuyente", {}).get("nombre"),
                        "status": data.get("Contribuyente", {}).get("estado"),
                        "activities": data.get("Contribuyente", {}).get("actividades", []),
                        "address": data.get("Contribuyente", {}).get("domicilio"),
                    }

            return {"error": "Could not fetch AFIP data", "cuit": cuit_clean}

        except Exception as e:
            return {"error": f"AFIP lookup failed: {str(e)}", "cuit": cuit_clean}

    def list_related_companies(self, cuit: str) -> dict:
        """Find companies that share bid-rotation findings with the given CUIT."""
        related = {}

        for row in self.findings.get("bid_rotation", []):
            if row.get("cuit_1") == cuit:
                other = row.get("cuit_2")
                if other not in related:
                    related[other] = {"name": row.get("company_2"), "connections": []}
                related[other]["connections"].append({
                    "type": "bid_rotation",
                    "times_together": row.get("times_together"),
                    "their_wins": row.get("c2_wins"),
                    "our_wins": row.get("c1_wins")
                })
            elif row.get("cuit_2") == cuit:
                other = row.get("cuit_1")
                if other not in related:
                    related[other] = {"name": row.get("company_1"), "connections": []}
                related[other]["connections"].append({
                    "type": "bid_rotation",
                    "times_together": row.get("times_together"),
                    "their_wins": row.get("c1_wins"),
                    "our_wins": row.get("c2_wins")
                })

        if not related:
            return {"cuit": cuit, "related_companies": [], "message": "No related companies found in bid rotation patterns"}

        return {
            "cuit": cuit,
            "related_companies": [
                {"cuit": k, **v} for k, v in sorted(
                    related.items(),
                    key=lambda x: sum(c.get("times_together", 0) for c in x[1]["connections"]),
                    reverse=True
                )[:20]
            ]
        }

    def get_entity_risk_breakdown(self, cuit: str) -> dict:
        """Explain a company's smart-scoring risk: contributions, synergies, confidence."""
        data = self.company_index.get(cuit)
        rs = (data or {}).get("risk_score")
        if not rs:
            return {"error": f"No risk score for CUIT {cuit} in the latest detection run."}
        return {
            "cuit": cuit,
            "company": rs.get("company"),
            "score": rs.get("score"),
            "base_score": rs.get("base_score"),
            "confidence": rs.get("confidence"),
            "flags": rs.get("flags"),
            "evidence_breakdown": rs.get("evidence_breakdown"),
        }

    def _neighborhood_rows(self, check_key: str, cuit: str, fields: list, list_fields: dict) -> list:
        """Collect this company's rows from a cartel check, projecting selected fields."""
        out = []
        for row in self.findings.get(check_key, []):
            if row.get("provider_cuit") != cuit:
                continue
            item = {f: row.get(f) for f in fields}
            for dst, src in list_fields.items():
                item[dst] = [_flatten_list_item(m) for m in (row.get(src) or [])]
            out.append(item)
        return out

    def get_network_neighborhood(self, cuit: str) -> dict:
        """Map a company's co-bidding/collusion network from the cartel-check findings."""
        rings = self._neighborhood_rows(
            "bid_rotation_ring", cuit,
            ["ring_id", "ring_size", "shared_processes", "member_wins", "rotation_pct", "cobid_strength"],
            {"co_members": "co_members"},
        )
        clusters = self._neighborhood_rows(
            "shared_contact_cluster", cuit,
            ["cluster_id", "cluster_size", "cobid_processes", "distinct_winners"],
            {"co_members": "co_members", "shared_contacts": "shared_contacts"},
        )
        communities = self._neighborhood_rows(
            "cobid_community", cuit,
            ["community_id", "community_size", "density", "cohesion_pct"],
            {"co_members": "co_members"},
        )
        triads = [
            {k: row.get(k) for k in ("authorizer", "unit_code", "unit_name", "contracts", "authorizer_pct", "unit_pct", "real_ars")}
            for row in self.findings.get("authorizer_provider_ring", [])
            if row.get("provider_cuit") == cuit
        ]

        rs = (self.company_index.get(cuit) or {}).get("risk_score") or {}
        centrality = (rs.get("evidence_breakdown") or {}).get("features")

        if not (rings or clusters or communities or triads or centrality):
            return {"cuit": cuit, "message": "No cartel-network signals found for this company in the latest run."}

        return {
            "cuit": cuit,
            "rings": rings,
            "contact_clusters": clusters,
            "communities": communities,
            "authorizer_triads": triads,
            "centrality": centrality,
        }

    def execute_tool(self, name: str, input_data: dict) -> dict:
        """Dispatch a tool call by name to the corresponding method."""
        if name == "get_company_data":
            return self.get_company_data(input_data["cuit"])
        elif name == "get_tender_data":
            return self.get_tender_data(input_data["process"])
        elif name == "query_neo4j":
            return self.query_neo4j(input_data["cypher"])
        elif name == "search_web":
            return self.search_web(input_data["query"])
        elif name == "lookup_afip":
            return self.lookup_afip(input_data["cuit"])
        elif name == "list_related_companies":
            return self.list_related_companies(input_data["cuit"])
        elif name == "get_entity_risk_breakdown":
            return self.get_entity_risk_breakdown(input_data["cuit"])
        elif name == "get_network_neighborhood":
            return self.get_network_neighborhood(input_data["cuit"])
        else:
            return {"error": f"Unknown tool: {name}"}


class ClaudeClient:
    """Anthropic Claude client with tool use."""

    def __init__(self, tools: CoimaTools):
        self.tools = tools
        self.client = None

        if HAS_ANTHROPIC:
            from src.api.config import get_settings
            api_key = get_settings().anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
            if api_key:
                self.client = anthropic.Anthropic(api_key=api_key)

    def is_available(self) -> bool:
        return self.client is not None

    def _language_instruction(self, investigation: dict) -> str:
        from src.i18n.translator import ai_language_instruction
        return ai_language_instruction(investigation.get("_locale", "en"))

    def _build_system_prompt(self, investigation: dict) -> str:
        """Build the system prompt with the investigation's context snapshot."""
        subjects_desc = []
        for s in investigation.get("subjects", []):
            if s["type"] == "company":
                subjects_desc.append(f"- Company: {s['name']} (CUIT: {s['id']})")
            else:
                subjects_desc.append(f"- Tender: {s['id']}")

        return f"""You are an expert corruption investigator assistant analyzing public procurement data in Argentina (COMPR.AR platform).

CURRENT INVESTIGATION: {investigation.get('title', 'Untitled')}
Status: {investigation.get('status', 'open')}
Created: {investigation.get('created_at', 'Unknown')}

SUBJECTS UNDER INVESTIGATION:
{chr(10).join(subjects_desc) if subjects_desc else 'None yet'}

CONTEXT (Including findings summaries for subjects):
{json.dumps(investigation.get('context_snapshot', {}), default=str)}

DATABASE SCHEMA (Neo4j):
- Nodes: Process, Provider, ContractingUnit, Organization, Bid, BidLine, ContractualDocument, ContractLine, ProvisionRequest, Authorizer, Phone, Email, Address
- Process: process_number, status, modality, opening_date
- Provider: cuit, business_name, address, city, province, phone, email
- ContractingUnit: code, name, saf_code
- Bid: total_amount, currency, status  |  ContractualDocument: document_number, document_type, total_amount, status, process_number
- Key relationships: MANAGED_BY (Process→ContractingUnit), HAS_BID (Process→Bid), SUBMITTED_BY (Bid→Provider), GENERATES (Process→ContractualDocument), AWARDED_TO (ContractualDocument→Provider), HAS_PHONE/HAS_EMAIL/HAS_ADDRESS (Organization/ContractingUnit/Provider→Phone/Email/Address)

You have access to tools to query the corruption detection database, explain risk scores (get_entity_risk_breakdown), map collusion networks (get_network_neighborhood), execute Neo4j queries, search the web, and look up AFIP data. Use these tools to gather evidence and provide thorough analysis.

{ANALYSIS_GUIDANCE}

Be precise with data. Cite specific process numbers, dates, and amounts when available.
{self._language_instruction(investigation)}"""

    def chat(
        self,
        investigation: dict,
        user_message: str,
        stream: bool = False
    ) -> Generator[dict, None, None] | dict:
        """Stream a chat response, handling tool use rounds until the model finishes."""

        if not self.is_available():
            yield {"type": "error", "content": "Claude API not available. Set ANTHROPIC_API_KEY environment variable."}
            return

        messages = []
        for msg in investigation.get("chat_history", []):
            messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })
        messages.append({"role": "user", "content": user_message})

        system_prompt = self._build_system_prompt(investigation)

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                system=system_prompt,
                tools=TOOLS,
                messages=messages
            )

            while response.stop_reason == "tool_use":
                tool_results = []
                tool_calls = []

                for block in response.content:
                    if block.type == "tool_use":
                        tool_name = block.name
                        tool_input = block.input
                        tool_id = block.id

                        yield {
                            "type": "tool_use",
                            "tool": tool_name,
                            "input": tool_input
                        }

                        result = self.tools.execute_tool(tool_name, tool_input)

                        tool_calls.append({
                            "id": tool_id,
                            "name": tool_name,
                            "input": tool_input
                        })

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": json.dumps(result, default=str)
                        })

                        yield {
                            "type": "tool_result",
                            "tool": tool_name,
                            "result": result
                        }

                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})

                response = self.client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=4096,
                    system=system_prompt,
                    tools=TOOLS,
                    messages=messages
                )

            final_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    final_text += block.text

            yield {
                "type": "message",
                "content": final_text,
                "tool_calls": tool_calls if 'tool_calls' in dir() else []
            }

        except Exception as e:
            yield {
                "type": "error",
                "content": f"Claude API error: {str(e)}"
            }

    def generate_report(
        self,
        investigation: dict,
        report_type: str
    ) -> Generator[dict, None, None]:
        """Generate a structured report by replaying the report prompt through chat()."""

        if report_type not in REPORT_PROMPTS:
            yield {"type": "error", "content": f"Unknown report type: {report_type}"}
            return

        prompt = REPORT_PROMPTS[report_type]

        full_prompt = f"""{prompt}

First, use the available tools to gather all relevant data about the investigation subjects. Then synthesize the information into the report format described above.

Investigation subjects to analyze:
{json.dumps([s for s in investigation.get('subjects', [])])}
"""

        yield from self.chat(investigation, full_prompt)
