# PLACEHOLDER - not implemented yet
"""
Postflop leak-detection report (Part 3).

Analyses Hero's postflop play and produces a structured report covering:

River calls
  - Win-rate check: win% must exceed call / (pot + call - fees); flags
    all calls where it falls short, ordered from most negative to least.
  - Flop and turn calls reported as hints (smaller sample, directional only).

River value betting
  - Flags spots where Hero checked back when bet would be +EV:
    break-even threshold = 50% after rake and re-raise equity.
  - Counts missed value bets per hand-strength bucket.
  - Bet-vs-check EV hints for flop and turn.

Showdown vs non-showdown winnings
  - Splits net $ won into showdown and non-showdown components per spot.

Frequency report
  - C-bet frequency (flop bet after being preflop aggressor), by pot type.
  - Fold-to-c-bet frequency.
  - Double-barrel (turn bet after flop c-bet) frequency.
  - Check-raise frequency.
  - Fold-to-raise frequency.
  All reported as a percentage with sample size; compared against
  a population baseline where available.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RiverCallResult:
    """Outcome of a single river call decision."""
    spot_label: str
    call_amount: float
    pot_before_call: float
    win_rate: float           # Hero's actual win rate in this spot (0.0–1.0)
    break_even_rate: float    # required win rate = call / (pot + call - fees)
    ev_estimate: float        # (win_rate - break_even_rate) * (pot + call - fees)
    sample_size: int


@dataclass
class MissedValueBet:
    """A spot where Hero checked when a bet would have been +EV."""
    spot_label: str
    hand_strength: str
    check_winnings: float     # average $ won when checking in this spot
    bet_ev_estimate: float    # estimated EV of betting (from similar spots)
    missed_ev: float          # bet_ev_estimate - check_winnings
    sample_size: int


@dataclass
class FrequencyStats:
    """Action frequency for a single spot type."""
    action: str               # e.g. "c-bet", "fold-to-cbet", "barrel", "check-raise"
    spot_label: str
    frequency: float          # 0.0–1.0
    sample_size: int
    baseline: float | None    # population baseline if available


@dataclass
class PostflopReport:
    """Full postflop analysis report."""
    river_call_leaks: list[RiverCallResult] = field(default_factory=list)
    flop_call_hints: list[RiverCallResult] = field(default_factory=list)
    turn_call_hints: list[RiverCallResult] = field(default_factory=list)
    missed_value_bets: list[MissedValueBet] = field(default_factory=list)
    frequency_stats: list[FrequencyStats] = field(default_factory=list)
    showdown_winnings: float = 0.0
    non_showdown_winnings: float = 0.0


def build_postflop_report(
    hands: list[dict[str, Any]],
    fee_rate: float = 0.05,
) -> PostflopReport:
    """
    Build the full postflop report from a list of parsed hands.

    Args:
        hands: Parsed hand dictionaries from the database, each containing
               postflop decision records.
        fee_rate: Rake + RB effective fee rate (default 5%).

    Returns:
        A PostflopReport with all sections populated.

    Raises:
        NotImplementedError: This function is not yet implemented.
    """
    raise NotImplementedError("planned")


def render_postflop_report(report: PostflopReport) -> str:
    """
    Render a PostflopReport to a human-readable text string.

    Args:
        report: A populated PostflopReport instance.

    Returns:
        Multi-section text report suitable for printing or saving to file.

    Raises:
        NotImplementedError: This function is not yet implemented.
    """
    raise NotImplementedError("planned")
