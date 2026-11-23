# PLACEHOLDER - not implemented yet
"""
Final ranked leak report (Part 5).

Aggregates outputs from the preflop report (Part 2), postflop report
(Part 3), and ML bluff scorer (Part 4) into a single ranked list of
leaks ordered by estimated money lost per 100 hands (BB/100).

Each leak entry includes:
  - A human-readable description of the leak.
  - The estimated cost in BB/100.
  - A 90% bootstrap confidence interval.
  - Whether it passed the discovery/confirmation holdout test.
  - The sample size driving the estimate.

Separate ranked lists are produced for:
  - Preflop leaks (open sizing, 3-bet frequency, fold-to-3bet, etc.)
  - Postflop leaks (call accuracy, missed value, missed bluffs, etc.)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LeakEntry:
    """A single leak with its cost and statistical support."""
    rank: int
    category: str             # "preflop" | "postflop"
    description: str
    cost_bb_per_100: float    # positive = losing money
    ci_low: float             # 5th percentile of bootstrap distribution
    ci_high: float            # 95th percentile of bootstrap distribution
    confirmed: bool           # passed holdout confirmation test
    sample_size: int


@dataclass
class LeakReport:
    """Full ranked leak report."""
    preflop_leaks: list[LeakEntry] = field(default_factory=list)
    postflop_leaks: list[LeakEntry] = field(default_factory=list)
    total_estimated_cost_bb_per_100: float = 0.0


def build_leak_report(
    preflop_results: list[dict[str, Any]],
    postflop_report: Any,
    bluff_results: list[Any],
    hands: list[dict[str, Any]],
) -> LeakReport:
    """
    Build the final ranked leak report from all analysis outputs.

    Args:
        preflop_results: Output from the preflop report module.
        postflop_report: PostflopReport instance from postflop_report.py.
        bluff_results:   List of BluffEVResult from ml/bluff_ev.py.
        hands:           All parsed hand dicts (used for bootstrap CIs).

    Returns:
        A LeakReport with separate ranked preflop and postflop leak lists.

    Raises:
        NotImplementedError: This function is not yet implemented.
    """
    raise NotImplementedError("planned")


def render_leak_report(report: LeakReport) -> str:
    """
    Render the full leak report as a formatted text string.

    Args:
        report: A populated LeakReport instance.

    Returns:
        Human-readable multi-section text report.

    Raises:
        NotImplementedError: This function is not yet implemented.
    """
    raise NotImplementedError("planned")
