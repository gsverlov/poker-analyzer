# PLACEHOLDER - not implemented yet
"""
Board texture classification for postflop analysis (Part 3).

Classifies a flop/turn/river board along several dimensions:
- High-card rank of the board (ace-high, king-high, etc.)
- Pairing (unpaired, paired, trips on board)
- Suit texture (monotone, two-tone, rainbow)
- Connectedness (connected, one-gap, disconnected)

Used by postflop_labels.py and postflop_report.py to bucket spots.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence


@dataclass
class BoardTexture:
    """Describes the texture of a board at a given street."""
    high_card: str          # e.g. "A", "K", "T"
    is_paired: bool         # True if the board contains a pair
    is_trips: bool          # True if the board contains three of a kind
    suit_texture: str       # "monotone" | "two-tone" | "rainbow"
    is_connected: bool      # True if at least two cards are adjacent in rank
    has_straight_draw: bool # True if three cards span four consecutive ranks
    has_flush_draw: bool    # True if two or more cards share a suit


def classify_board(cards: Sequence[str]) -> BoardTexture:
    """
    Classify a board given a list of card strings.

    Args:
        cards: Sequence of card strings, e.g. ["Ah", "Kd", "2c"].
               Must contain 3–5 cards (flop through river).

    Returns:
        A BoardTexture dataclass with all texture fields populated.

    Raises:
        NotImplementedError: This function is not yet implemented.
        ValueError: If fewer than 3 or more than 5 cards are supplied.
    """
    raise NotImplementedError("planned")


def board_texture_label(texture: BoardTexture) -> str:
    """
    Return a short human-readable label for a BoardTexture.

    E.g. "A-high rainbow connected", "K-high monotone paired".

    Args:
        texture: A BoardTexture instance from classify_board().

    Returns:
        A short descriptive string for use in spot labels.

    Raises:
        NotImplementedError: This function is not yet implemented.
    """
    raise NotImplementedError("planned")
