# PLACEHOLDER - not implemented yet
"""
Board-relative hand-strength classification for postflop analysis (Part 3).

Maps Hero's hole cards + the board to a hand-strength category so that
postflop decisions can be bucketed by equity class rather than raw hand.

Categories (from strongest to weakest made hands, then draws):
  Made hands: overpair, top-pair-top-kicker, top-pair-good-kicker,
              top-pair-weak-kicker, second-pair, weak-pair,
              bottom-pair, underpair, no-pair-showdown, no-pair-air
  Draws:      nut-flush-draw, flush-draw, nut-straight-draw,
              straight-draw, combo-draw, gutshot
  Blockers:   key-blocker (holds the nut card for the board's main draw)

Each category can be decorated with a 'has_key_blocker' flag.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence
from poker_analyzer.board_texture import BoardTexture  # noqa: F401 (imported for type use)


HAND_STRENGTH_CATEGORIES = [
    "overpair",
    "top-pair-top-kicker",
    "top-pair-good-kicker",
    "top-pair-weak-kicker",
    "second-pair",
    "weak-pair",
    "bottom-pair",
    "underpair",
    "no-pair-showdown",
    "no-pair-air",
    "nut-flush-draw",
    "flush-draw",
    "nut-straight-draw",
    "straight-draw",
    "combo-draw",
    "gutshot",
]


@dataclass
class HandStrength:
    """Board-relative hand classification for a specific holding."""
    category: str           # one of HAND_STRENGTH_CATEGORIES
    has_key_blocker: bool   # True if Hero holds the nut blocker for the board's primary draw
    equity_estimate: float  # rough equity vs a balanced range, 0.0–1.0 (requires equity cache)


def classify_hand_strength(
    hero_cards: Sequence[str],
    board_cards: Sequence[str],
    texture: "BoardTexture",
) -> HandStrength:
    """
    Classify Hero's hand relative to the board.

    Args:
        hero_cards: Hero's two hole cards, e.g. ["Ah", "Kd"].
        board_cards: Community cards (3–5 cards).
        texture: Pre-computed BoardTexture for board_cards.

    Returns:
        A HandStrength dataclass describing the hand's category,
        blocker status, and rough equity estimate.

    Raises:
        NotImplementedError: This function is not yet implemented.
        ValueError: If hero_cards does not contain exactly 2 cards.
    """
    raise NotImplementedError("planned")
