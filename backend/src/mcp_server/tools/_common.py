"""Shared tool annotations and row-trimming helpers."""

from __future__ import annotations

from typing import Any, Dict, List

from mcp.types import ToolAnnotations

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITES_CASE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)


def trim_findings(findings: Dict[str, List[Any]], max_rows: int) -> Dict[str, dict]:
    """{check: rows} -> {check: {total, rows[:max_rows]}} so one busy entity cannot flood the context."""
    return {
        check: {"total": len(rows), "rows": list(rows)[:max_rows]}
        for check, rows in findings.items()
        if rows
    }
