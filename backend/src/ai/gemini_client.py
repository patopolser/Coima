"""
src/ai/gemini_client.py - Google Gemini client with tool use, mirroring the
Claude client's surface so investigations and reports can switch backends
transparently.
"""

import os
import json
from typing import Generator

try:
    from google import genai
    from google.genai import types
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

from src.ai.claude_client import CoimaTools, REPORT_PROMPTS, ANALYSIS_GUIDANCE


def get_gemini_tools():
    """Translate the shared TOOLS catalog into Gemini's FunctionDeclaration shape."""
    if not HAS_GEMINI:
        return []

    return [
        types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="get_company_data",
                    description="Get all data about a company from the corruption detection system, including risk score, flags, and all findings where this company appears. Use this to understand a company's involvement in suspicious patterns.",
                    parameters={
                        "type": "OBJECT",
                        "properties": {
                            "cuit": {"type": "STRING", "description": "The CUIT (tax ID) of the company to look up"}
                        },
                        "required": ["cuit"]
                    }
                ),
                types.FunctionDeclaration(
                    name="get_tender_data",
                    description="Get detailed information about a specific tender/licitación, including bidders, winner, and any flags. Use this to analyze a specific procurement process.",
                    parameters={
                        "type": "OBJECT",
                        "properties": {
                            "process": {"type": "STRING", "description": "The process number"}
                        },
                        "required": ["process"]
                    }
                ),
                types.FunctionDeclaration(
                    name="query_neo4j",
                    description="Execute a read-only Cypher query against the Neo4j graph database of public procurement data from COMPR.AR Argentina. Nodes: Process (process_number, status, modality, opening_date), Provider (cuit, business_name, address, city, province, phone, email), ContractingUnit (code, name, saf_code), Organization (saf_code, name), Bid (total_amount=TOTAL of all lines for that provider in the process, currency, status — one Bid per provider/process), BidLine (line_number, alternative_number, offered_quantity, unit_price, total_per_line — use this for per-line price analysis between providers), ContractualDocument (document_number, document_type, total_amount, status, process_number), ContractLine, ProvisionRequest, Authorizer, Phone (value), Email (value), Address (value). Relationships: MANAGED_BY (Process→ContractingUnit), BELONGS_TO (ContractingUnit→Organization), HAS_BID (Process→Bid), SUBMITTED_BY (Bid→Provider), HAS_BID_LINE (Bid→BidLine), FOR_LINE_ITEM (BidLine→LineItem), GENERATES (Process→ContractualDocument), AWARDED_TO (ContractualDocument→Provider), HAS_CONTRACT_LINE (ContractualDocument→ContractLine), AUTHORIZED_BY (ContractualDocument/ProvisionRequest→Authorizer), HAS_PHONE/HAS_EMAIL/HAS_ADDRESS (Organization/ContractingUnit/Provider→Phone/Email/Address), INVITES (Process→Provider), HAS_PROVISION_REQUEST (ContractualDocument→ProvisionRequest), FULFILLED_BY (ProvisionRequest→Provider). IMPORTANT: To compare prices between competing providers use BidLine (join on line_number), NOT Bid.total_amount.",
                    parameters={
                        "type": "OBJECT",
                        "properties": {
                            "cypher": {"type": "STRING", "description": "A read-only Cypher query"}
                        },
                        "required": ["cypher"]
                    }
                ),
                types.FunctionDeclaration(
                    name="search_web",
                    description="Search the web for news and information about a company or person.",
                    parameters={
                        "type": "OBJECT",
                        "properties": {
                            "query": {"type": "STRING", "description": "Search query"}
                        },
                        "required": ["query"]
                    }
                ),
                types.FunctionDeclaration(
                    name="lookup_afip",
                    description="Look up public AFIP (tax authority) data for a company by CUIT.",
                    parameters={
                        "type": "OBJECT",
                        "properties": {
                            "cuit": {"type": "STRING", "description": "The CUIT to look up"}
                        },
                        "required": ["cuit"]
                    }
                ),
                types.FunctionDeclaration(
                    name="list_related_companies",
                    description="Find companies that appear together with a given company in bid rotation patterns or the same tenders.",
                    parameters={
                        "type": "OBJECT",
                        "properties": {
                            "cuit": {"type": "STRING", "description": "The CUIT of the company"}
                        },
                        "required": ["cuit"]
                    }
                ),
                types.FunctionDeclaration(
                    name="get_entity_risk_breakdown",
                    description="Get the smart-scoring breakdown behind a company's risk score: per-check contribution (weight x intensity), matched syndromes that multiplied the score, the synergy multiplier, the confidence count of independent corroborating vectors, and co-bidding network position. Explains WHY a company scores as it does.",
                    parameters={
                        "type": "OBJECT",
                        "properties": {
                            "cuit": {"type": "STRING", "description": "The CUIT to explain"}
                        },
                        "required": ["cuit"]
                    }
                ),
                types.FunctionDeclaration(
                    name="get_network_neighborhood",
                    description="Map a company's collusion network: bid-rotation rings (members, shared processes, win-rotation %), shared-contact clusters, dense co-bidding communities, authorizer-unit-provider triads, and co-bidding centrality (degree, betweenness). Identifies cartels and the companies to investigate alongside this one.",
                    parameters={
                        "type": "OBJECT",
                        "properties": {
                            "cuit": {"type": "STRING", "description": "The CUIT whose network to map"}
                        },
                        "required": ["cuit"]
                    }
                )
            ]
        )
    ]


class GeminiClient:
    def __init__(self, tools: CoimaTools):
        self.tools = tools
        self.client = None

        from src.api.config import get_settings
        api_key = get_settings().gemini_api_key or os.environ.get("GEMINI_API_KEY")
        if HAS_GEMINI and api_key:
            self.client = genai.Client(api_key=api_key)

    def is_available(self) -> bool:
        return self.client is not None

    def _language_instruction(self, investigation: dict) -> str:
        from src.i18n.translator import ai_language_instruction
        return ai_language_instruction(investigation.get("_locale", "en"))

    def _build_system_prompt(self, investigation: dict) -> str:
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

    def chat(self, investigation: dict, user_message: str) -> Generator[dict, None, None]:
        if not self.is_available():
            yield {"type": "error", "content": "Gemini API not available. Set GEMINI_API_KEY environment variable."}
            return

        chat_history = []
        for msg in investigation.get("chat_history", []):
            role = "user" if msg["role"] == "user" else "model"
            chat_history.append(types.Content(role=role, parts=[types.Part(text=msg["content"])]))

        system_instruction = self._build_system_prompt(investigation)
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=get_gemini_tools(),
            temperature=0.2,
        )

        try:
            chat = self.client.chats.create(model="gemini-2.5-flash", config=config, history=chat_history)
            response = chat.send_message(user_message)

            while True:
                has_tool_call = False
                for part in response.parts:
                    if part.function_call:
                        has_tool_call = True
                        tool_name = part.function_call.name
                        tool_args = {k: v for k, v in part.function_call.args.items()}

                        yield {
                            "type": "tool_use",
                            "tool": tool_name,
                            "input": tool_args
                        }

                        result = self.tools.execute_tool(tool_name, tool_args)

                        yield {
                            "type": "tool_result",
                            "tool": tool_name,
                            "result": result
                        }

                        response = chat.send_message(
                            types.Part(
                                function_response=types.FunctionResponse(
                                    name=tool_name,
                                    response={"result": result}
                                )
                            )
                        )
                        break

                if not has_tool_call:
                    break

            if response.text:
                yield {
                    "type": "message",
                    "content": response.text
                }

        except Exception as e:
            yield {
                "type": "error",
                "content": f"Gemini API error: {str(e)}"
            }

    def generate_report(self, investigation: dict, report_type: str) -> Generator[dict, None, None]:
        if report_type not in REPORT_PROMPTS:
            yield {"type": "error", "content": f"Unknown report type: {report_type}"}
            return

        prompt = REPORT_PROMPTS[report_type]
        full_prompt = f"{prompt}\n\nFirst, use the available tools to gather all relevant data about the investigation subjects. Then synthesize the information into the report format described above.\n\nInvestigation subjects to analyze:\n{json.dumps([s for s in investigation.get('subjects', [])])}\n"

        yield from self.chat(investigation, full_prompt)
