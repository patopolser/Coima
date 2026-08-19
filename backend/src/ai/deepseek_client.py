"""
src/ai/deepseek_client.py - DeepSeek client backed by NVIDIA NIM's
OpenAI-compatible chat completions API.

Mirrors the Claude and Gemini clients so the investigations layer can switch
backends through a single `model` field. When tools are disabled (the default
on NIM) the model receives a compacted context snapshot in the system prompt
so it can analyse the investigation without round-tripping tool calls.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from typing import Generator

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

from src.ai.claude_client import REPORT_PROMPTS, TOOLS, CoimaTools, ANALYSIS_GUIDANCE
from src.api.config import get_settings


def _to_openai_tools() -> list[dict]:
    """Convert Anthropic-style tool definitions to OpenAI/NVIDIA format."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            },
        }
        for tool in TOOLS
    ]


class DeepSeekClient:
    """DeepSeek on NVIDIA NIM with OpenAI-compatible tool calls."""

    def __init__(self, tools: CoimaTools):
        settings = get_settings()
        self.tools = tools
        self.api_key = (
            settings.deepseek_api_key
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("NVIDIA_API_KEY")
            or os.environ.get("NGC_API_KEY")
        )
        self.base_url = settings.deepseek_base_url.rstrip("/")
        self.model = self._normalize_model(settings.deepseek_model)
        self.enable_tools = settings.deepseek_enable_tools
        self.temperature = settings.deepseek_temperature
        self.top_p = settings.deepseek_top_p
        self.max_tokens = settings.deepseek_max_tokens

    def is_available(self) -> bool:
        return HAS_REQUESTS and bool(self.api_key)

    def _normalize_model(self, model: str) -> str:
        # NVIDIA NIM requires the "deepseek-ai/" namespace prefix; other
        # OpenAI-compatible endpoints accept the bare model id.
        if "integrate.api.nvidia.com" not in self.base_url:
            return model
        if model in {"deepseek-v4-pro", "deepseek-v4-flash"}:
            return f"deepseek-ai/{model}"
        return model

    def _language_instruction(self, investigation: dict) -> str:
        from src.i18n.translator import ai_language_instruction
        return ai_language_instruction(investigation.get("_locale", "en"))

    def _compact_context(self, context: dict) -> dict:
        """Trim the investigation context snapshot down to fit the prompt budget."""
        compact = {
            "risk_scores": context.get("risk_scores", {}),
            "findings_summary": context.get("findings_summary", {}),
            "findings_totals": context.get("findings_totals", {}),
            "notes": context.get("notes", [])[-10:],
        }

        samples = {}
        for cuit, by_check in context.get("findings_samples", {}).items():
            samples[cuit] = {
                check_key: rows[:10]
                for check_key, rows in by_check.items()
            }
        if samples:
            compact["findings_samples"] = samples

        tender_findings = {}
        for process, by_check in context.get("tender_findings", {}).items():
            tender_findings[process] = {}
            for check_key, payload in by_check.items():
                tender_findings[process][check_key] = {
                    **payload,
                    "rows": payload.get("rows", [])[:10],
                    "included": min(payload.get("included", 0), 10),
                    "truncated": payload.get("total", 0) > 10,
                }
        if tender_findings:
            compact["tender_findings"] = tender_findings

        return compact

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

CONTEXT (risk scores, finding summaries, sampled finding rows, tender matches, and investigator notes):
{json.dumps(self._compact_context(investigation.get('context_snapshot', {})), default=str)}

DATABASE SCHEMA (Neo4j):
- Nodes: Process, Provider, ContractingUnit, Organization, Bid, BidLine, ContractualDocument, ContractLine, ProvisionRequest, Authorizer, Phone, Email, Address
- Process: process_number, status, modality, opening_date
- Provider: cuit, business_name, address, city, province, phone, email
- ContractingUnit: code, name, saf_code
- Bid: total_amount, currency, status  |  ContractualDocument: document_number, document_type, total_amount, status, process_number
- Key relationships: MANAGED_BY (Process->ContractingUnit), HAS_BID (Process->Bid), SUBMITTED_BY (Bid->Provider), GENERATES (Process->ContractualDocument), AWARDED_TO (ContractualDocument->Provider), HAS_PHONE/HAS_EMAIL/HAS_ADDRESS (Organization/ContractingUnit/Provider->Phone/Email/Address)

The context snapshot already includes the most relevant data known for the investigation subjects (including each subject's risk-score evidence_breakdown: synergies, per-check contributions and co-bidding centrality). If external tools are available in this request, use them to gather more evidence (get_entity_risk_breakdown and get_network_neighborhood explain scores and map cartels); otherwise, analyze the provided context directly and say when more data would be needed.

{ANALYSIS_GUIDANCE}

Be precise with data. Cite specific process numbers, dates, and amounts when available.
{self._language_instruction(investigation)}"""

    def _payload(self, messages: list[dict], stream: bool) -> dict:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "chat_template_kwargs": {"thinking": False},
            "stream": stream,
        }
        if self.enable_tools:
            payload["tools"] = _to_openai_tools()
            payload["tool_choice"] = "auto"
        return payload

    def _extract_text(self, message: dict) -> str:
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and item.get("text"):
                    parts.append(item["text"])
            return "".join(parts)
        return ""

    def _post_chat(self, messages: list[dict]) -> tuple[dict, dict]:
        started = time.perf_counter()
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=self._payload(messages, stream=False),
            timeout=(30, 900),
        )
        latency_ms = int((time.perf_counter() - started) * 1000)

        meta = {
            "endpoint": f"{self.base_url}/chat/completions",
            "model": self.model,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "request_id_header": response.headers.get("x-request-id") or response.headers.get("request-id"),
        }

        if response.status_code in {401, 403}:
            raise RuntimeError(
                "DeepSeek NVIDIA API rejected the request. Check COIMA_DEEPSEEK_API_KEY "
                "or DEEPSEEK_API_KEY, and confirm the key has access to the configured model."
            )
        if response.status_code == 202:
            raise RuntimeError(
                "DeepSeek NVIDIA returned 202 pending. Try again in a moment or use deepseek-ai/deepseek-v4-flash."
            )
        if not response.ok:
            body = response.text[:1000]
            raise RuntimeError(
                f"DeepSeek NVIDIA API error {response.status_code} at "
                f"{self.base_url}/chat/completions: {body}"
            )
        try:
            data = response.json()
        except Exception as exc:
            body = response.text[:1000]
            raise RuntimeError(f"DeepSeek NVIDIA returned non-JSON body: {body}") from exc

        meta["response_id"] = data.get("id")
        return data, meta

    def _post_chat_with_heartbeats(self, messages: list[dict]) -> Generator[dict, None, tuple[dict, dict] | None]:
        """Run _post_chat in a thread, emitting heartbeat events while we wait."""
        done = object()
        result_queue: queue.Queue = queue.Queue()

        def worker():
            try:
                result_queue.put(self._post_chat(messages))
            except Exception as exc:
                result_queue.put(exc)
            finally:
                result_queue.put(done)

        threading.Thread(target=worker, daemon=True).start()
        waited = 0
        while True:
            try:
                item = result_queue.get(timeout=10)
            except queue.Empty:
                waited += 10
                yield {
                    "type": "tool_result",
                    "tool": "deepseek_nvidia",
                    "result": {"status": "waiting", "seconds": waited},
                }
                continue

            if item is done:
                return None
            if isinstance(item, Exception):
                raise item
            return item

    def chat(self, investigation: dict, user_message: str) -> Generator[dict, None, None]:
        if not HAS_REQUESTS:
            yield {"type": "error", "content": "DeepSeek API not available. Install the requests library."}
            return
        if not self.api_key:
            yield {
                "type": "error",
                "content": "DeepSeek NVIDIA API key not configured. Set COIMA_DEEPSEEK_API_KEY or DEEPSEEK_API_KEY.",
            }
            return

        messages = [{"role": "system", "content": self._build_system_prompt(investigation)}]
        for msg in investigation.get("chat_history", []):
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": user_message})

        try:
            if not self.enable_tools:
                yield {
                    "type": "tool_use",
                    "tool": "deepseek_nvidia",
                    "input": {
                        "model": self.model,
                        "stream": False,
                        "thinking": False,
                        "temperature": self.temperature,
                        "top_p": self.top_p,
                        "max_tokens": self.max_tokens,
                    },
                }
                result = yield from self._post_chat_with_heartbeats(messages)
                if result is None:
                    yield {"type": "error", "content": "DeepSeek NVIDIA finished without returning data."}
                    return
                data, meta = result
                yield {"type": "tool_result", "tool": "deepseek_nvidia_http", "result": meta}
                choice = data.get("choices", [{}])[0]
                message = choice.get("message", {})
                content = self._extract_text(message)
                if content:
                    yield {"type": "message", "content": content}
                else:
                    preview = json.dumps(data, ensure_ascii=False, default=str)[:1500]
                    yield {"type": "error", "content": f"DeepSeek NVIDIA returned no message content: {preview}"}
                return

            # Tool-calling path: bounded loop guards against models that
            # never stop asking for more tools.
            for _ in range(8):
                data, meta = self._post_chat(messages)
                yield {"type": "tool_result", "tool": "deepseek_nvidia_http", "result": meta}
                choice = data.get("choices", [{}])[0]
                message = choice.get("message", {})
                tool_calls = message.get("tool_calls") or []

                if not tool_calls:
                    yield {"type": "message", "content": self._extract_text(message)}
                    return

                messages.append({
                    "role": "assistant",
                    "content": self._extract_text(message),
                    "tool_calls": tool_calls,
                })

                for call in tool_calls:
                    function = call.get("function", {})
                    tool_name = function.get("name")
                    raw_args = function.get("arguments") or "{}"
                    try:
                        tool_input = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except json.JSONDecodeError:
                        tool_input = {}

                    yield {"type": "tool_use", "tool": tool_name, "input": tool_input}
                    result = self.tools.execute_tool(tool_name, tool_input)
                    yield {"type": "tool_result", "tool": tool_name, "result": result}

                    messages.append({
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })

            yield {"type": "error", "content": "DeepSeek stopped after too many tool-call rounds."}
        except Exception as exc:
            yield {"type": "error", "content": f"DeepSeek NVIDIA API error: {str(exc)}"}

    def generate_report(self, investigation: dict, report_type: str) -> Generator[dict, None, None]:
        if report_type not in REPORT_PROMPTS:
            yield {"type": "error", "content": f"Unknown report type: {report_type}"}
            return

        prompt = REPORT_PROMPTS[report_type]
        data_instruction = (
            "First, use the available tools to gather all relevant data about the investigation subjects. "
            "Then synthesize the information into the report format described above."
            if self.enable_tools
            else
            "Use the investigation context already provided in the system prompt. If evidence appears incomplete, "
            "state what additional data should be queried next."
        )

        full_prompt = f"""{prompt}

{data_instruction}

Investigation subjects to analyze:
{json.dumps([s for s in investigation.get('subjects', [])])}
"""

        yield from self.chat(investigation, full_prompt)
