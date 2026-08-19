"""
src/detector/ - Public surface of the detector package.

Re-exports the names that run.py and the API layer import, so internal
refactors inside the package do not break those call sites.
"""

from neo4j import GraphDatabase  # re-exported for run.py compatibility

from .base import load_config, get
from .runner import run_detection, build_risk_scores, save_report

__all__ = [
    "GraphDatabase",
    "load_config",
    "get",
    "run_detection",
    "build_risk_scores",
    "save_report",
]
