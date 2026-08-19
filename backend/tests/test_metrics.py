"""
Unit tests for the pure cartel-scoring metrics (no Neo4j / networkx needed).

Run from backend/:  python -m pytest tests/test_metrics.py -q
"""

import math

from src.detector.analytics.metrics import (
    normalized_entropy,
    weighted_internal_density,
    win_distribution,
)


def test_normalized_entropy_even_is_one():
    # Perfectly even distribution → max entropy → 1.0
    assert normalized_entropy([5, 5, 5, 5]) == 1.0


def test_normalized_entropy_single_dominator_is_zero():
    # All wins to one member → no spread → 0.0
    assert normalized_entropy([10, 0, 0]) == 0.0
    assert normalized_entropy([7]) == 0.0


def test_normalized_entropy_empty_and_zero():
    assert normalized_entropy([]) == 0.0
    assert normalized_entropy([0, 0, 0]) == 0.0


def test_normalized_entropy_partial_rotation_between_zero_and_one():
    # Skewed-but-shared distribution sits strictly between 0 and 1
    h = normalized_entropy([8, 2])
    assert 0.0 < h < 1.0
    # Two-way even reference is exactly 1.0, so skew must be below it
    assert h < normalized_entropy([5, 5])


def test_weighted_internal_density():
    # 3 nodes → 3 possible pairs; 9 total internal weight → density 3.0
    assert weighted_internal_density(3, 9) == 3.0
    # Degenerate groups
    assert weighted_internal_density(1, 5) == 0.0
    assert weighted_internal_density(0, 0) == 0.0


def test_win_distribution_counts_members_only():
    outcomes = [
        {"process_number": "P1", "winners": ["A"]},
        {"process_number": "P2", "winners": ["B"]},
        {"process_number": "P3", "winners": ["A", "C"]},  # multi-winner process
        {"process_number": "P4", "winners": ["Z"]},        # Z not a member → ignored
        {"process_number": "P5", "winners": []},            # deserted → no win
    ]
    members = ["A", "B", "C"]
    dist = win_distribution(outcomes, members)
    assert dist == {"A": 2, "B": 1, "C": 1}


def test_win_distribution_includes_zero_win_members():
    outcomes = [{"winners": ["A"]}]
    dist = win_distribution(outcomes, ["A", "B"])
    assert dist["B"] == 0  # cover member present with zero wins
