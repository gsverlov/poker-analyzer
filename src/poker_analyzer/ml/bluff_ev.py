# PLACEHOLDER - not implemented yet
"""
Bluff EV calculation and missed-bluff scorer (Part 4).

For heads-up spots only, computes the expected value of a bet/bluff:

  EV(bet) = P(fold)  * (pot - fees)
           + P(call)  * (result when called)
           + P(raise) * (result when raised)

P(fold), P(call), P(raise) come from the ML model (ml/model.py).
"result when called" uses the equity estimate from hand_strength.py.
"result when raised" assumes Hero folds (conservative lower-bound EV).

Missed bluffs are identified by comparing EV(bet) to Hero's actual
average result when checking the same hand-strength / spot-label bucket.
Spots are ranked by (EV(bet) - EV(check)) * frequency * hands_played.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass
class BluffEVResult:
    """EV breakdown for a single bluff candidate."""
    spot_label: str
    hand_strength: str
    p_fold: float
    p_call: float
    p_raise: float
    ev_bet: float             # EV of betting (bluff)
    ev_check: float           # Hero's observed EV when checking
    missed_ev: float          # ev_bet - ev_check  (positive = missed bluff)
    sample_size: int


def compute_bluff_ev(
    decision: dict[str, Any],
    p_fold: float,
    p_call: float,
    p_raise: float,
    equity_if_called: float,
    pot: float,
    bet: float,
    fee_rate: float = 0.05,
) -> float:
    """
    Compute EV(bet) for a single bluff decision.

    Args:
        decision:         The parsed decision dict (for context/logging).
        p_fold:           Model's predicted fold probability.
        p_call:           Model's predicted call probability.
        p_raise:          Model's predicted raise probability.
        equity_if_called: Hero's equity vs opponent's calling range (0.0–1.0).
        pot:              Pot size before the bet (in BB).
        bet:              Proposed bet size (in BB).
        fee_rate:         Effective rake + RB rate.

    Returns:
        Expected value of betting, in BB.

    Raises:
        NotImplementedError: This function is not yet implemented.
        ValueError: If p_fold + p_call + p_raise does not sum to ~1.0.
    """
    raise NotImplementedError("planned")


def score_missed_bluffs(
    decisions: list[dict[str, Any]],
    model: Any,
    fee_rate: float = 0.05,
) -> list[BluffEVResult]:
    """
    Identify and rank spots where Hero missed a profitable bluff.

    Iterates over heads-up postflop spots where Hero checked, queries
    the ML model for fold/call/raise probabilities, computes EV(bet),
    and compares it to Hero's observed check EV in that bucket.

    Args:
        decisions: List of Hero's postflop check decisions (heads-up only).
        model:     Fitted classifier with predict_proba() method.
        fee_rate:  Effective rake + RB rate.

    Returns:
        List of BluffEVResult objects, sorted by missed_ev descending.

    Raises:
        NotImplementedError: This function is not yet implemented.
    """
    raise NotImplementedError("planned")
