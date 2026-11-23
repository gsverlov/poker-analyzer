# PLACEHOLDER - not implemented yet
"""
Feature extraction for the ML opponent model (Part 4).

Builds a design matrix where each row represents one opponent decision
facing a bet. The target variable is the opponent's response:
  0 = fold, 1 = call, 2 = raise.

Feature set per row:
  - street (flop/turn/river, encoded as int)
  - pot_type (srp/3bet/4bet/limped, encoded as int)
  - hero_position (BTN/CO/HJ/MP/EP/BB/SB, encoded as int)
  - villain_position (same encoding)
  - heads_up (bool)
  - effective_stack_bb (float)
  - stack_to_pot_ratio (float)
  - bet_fraction (bet size / pot before bet, float)
  - board_texture_* (one-hot or ordinal for high card, suit, connectedness)
  - hero_earlier_actions (sequence of action codes this street, encoded)
  - villain_earlier_actions (same)
  - hero_bet_sizes_this_street (average fraction, float)
  - num_raises_this_street (int)
  - villain_vpip (float, from other hands this session)
  - villain_hands_seen (int, this session)
  - stakes_bb (big blind amount in cents, int)
"""
from __future__ import annotations
from typing import Any
import numpy as np  # type: ignore


def extract_features(decisions: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    """
    Extract features and labels from a list of opponent-decision dicts.

    Args:
        decisions: Each dict must contain keys matching the feature set
                   described in this module's docstring, plus 'response'
                   (fold/call/raise) as the label.

    Returns:
        A tuple (X, y) where:
          X is a float32 numpy array of shape (n_samples, n_features).
          y is an int array of shape (n_samples,) with values 0/1/2.

    Raises:
        NotImplementedError: This function is not yet implemented.
    """
    raise NotImplementedError("planned")


def feature_names() -> list[str]:
    """
    Return the ordered list of feature names matching columns of X.

    Returns:
        List of string feature names in the same order as extract_features()
        produces them.

    Raises:
        NotImplementedError: This function is not yet implemented.
    """
    raise NotImplementedError("planned")
