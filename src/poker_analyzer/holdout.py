# PLACEHOLDER - not implemented yet
"""
Discovery / confirmation holdout split (Part 5).

Splits sessions into two non-overlapping sets by date:
  - Discovery set  (oldest 70% of sessions): used to identify leaks.
  - Confirmation set (newest 30% of sessions): used to validate leaks.

A leak is confirmed if:
  1. The estimate in the confirmation set points in the same direction
     (same sign) as in the discovery set.
  2. The magnitude in the confirmation set is at least half the
     magnitude in the discovery set.

This guards against reporting noise as leaks after multiple comparisons.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any


DISCOVERY_FRACTION = 0.70   # fraction of sessions used for discovery


@dataclass
class LeakConfirmation:
    """Result of testing a single leak candidate against the holdout set."""
    leak_name: str
    discovery_estimate: float    # effect size in discovery set (e.g. BB/100 lost)
    confirmation_estimate: float # effect size in confirmation set
    confirmed: bool              # True if direction matches and magnitude >= 50%


def split_sessions(
    hands: list[dict[str, Any]],
    discovery_fraction: float = DISCOVERY_FRACTION,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Split hands into discovery and confirmation sets by session date.

    Args:
        hands:               All parsed hand dicts with 'session_date' key.
        discovery_fraction:  Fraction of session dates in the discovery set.

    Returns:
        Tuple (discovery_hands, confirmation_hands).

    Raises:
        NotImplementedError: This function is not yet implemented.
    """
    raise NotImplementedError("planned")


def confirm_leak(
    leak_name: str,
    stat_fn: Any,
    discovery_hands: list[dict[str, Any]],
    confirmation_hands: list[dict[str, Any]],
) -> LeakConfirmation:
    """
    Test whether a leak found in the discovery set holds in confirmation.

    Args:
        leak_name:          Short name for the leak (used in output).
        stat_fn:            Callable(hands) -> float measuring the leak's
                            effect size (positive = losing money).
        discovery_hands:    Hands from the discovery set.
        confirmation_hands: Hands from the confirmation set.

    Returns:
        A LeakConfirmation dataclass indicating whether the leak is confirmed.

    Raises:
        NotImplementedError: This function is not yet implemented.
    """
    raise NotImplementedError("planned")
