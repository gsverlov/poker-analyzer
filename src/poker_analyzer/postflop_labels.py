# PLACEHOLDER - not implemented yet
"""
Spot-label generator for every Hero postflop decision (Part 3).

Produces a hierarchical label for each postflop action Hero faces or
takes, combining:
  - Street (flop / turn / river)
  - Pot type (single-raised / 3-bet / 4-bet / limped)
  - Preflop role (opener, caller, 3-bettor, cold-caller, BB-def, etc.)
  - Position relative to remaining opponents (in-position / out-of-position)
  - Number of players (heads-up / multiway)
  - Hand-strength category (from hand_strength.py)
  - Action faced and action taken (check / bet / call / raise / fold)

Coarse labels are always produced; finer sub-labels are added only when
the sample in that bucket contains enough hands to be statistically
meaningful (>= 30 hands by default).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any


MIN_HANDS_FOR_FINE_LABEL = 30  # minimum sample to produce a fine-grained label


@dataclass
class PostflopSpotLabel:
    """Full hierarchical label for a single Hero postflop decision."""
    street: str               # "flop" | "turn" | "river"
    pot_type: str             # "srp" | "3bet" | "4bet" | "limped"
    preflop_role: str         # e.g. "opener", "caller", "3bettor", "bb-def"
    position: str             # "ip" (in position) | "oop" (out of position)
    heads_up: bool            # True if only two players remain postflop
    hand_strength: str        # category string from hand_strength.py
    action_faced: str         # "check" | "bet" | "raise" (the opponent's action)
    action_taken: str         # "check" | "bet" | "call" | "raise" | "fold"
    coarse_label: str         # always populated, e.g. "river-srp-ip-hu-call"
    fine_label: str | None    # populated only when sample >= MIN_HANDS_FOR_FINE_LABEL


def build_postflop_label(decision: dict[str, Any]) -> PostflopSpotLabel:
    """
    Build a PostflopSpotLabel from a parsed hand-history decision dict.

    Args:
        decision: Dictionary produced by the hand-history parser containing
                  at minimum keys: 'street', 'pot_type', 'preflop_role',
                  'position', 'players_remaining', 'hero_cards',
                  'board_cards', 'action_faced', 'action_taken'.

    Returns:
        A PostflopSpotLabel with both coarse_label and (if sample permits)
        fine_label populated.

    Raises:
        NotImplementedError: This function is not yet implemented.
        KeyError: If a required key is missing from decision.
    """
    raise NotImplementedError("planned")


def label_all_postflop_decisions(hands: list[dict[str, Any]]) -> list[PostflopSpotLabel]:
    """
    Apply build_postflop_label to every postflop decision in a hand list.

    Args:
        hands: List of parsed hand dictionaries from the database.

    Returns:
        List of PostflopSpotLabel objects, one per Hero postflop decision.

    Raises:
        NotImplementedError: This function is not yet implemented.
    """
    raise NotImplementedError("planned")
