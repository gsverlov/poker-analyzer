# PLACEHOLDER - not implemented yet
"""
Tilt and fatigue detection module (Part 5).

Analyses changes in Hero's play quality after:
  - Large downswings within a session (losing >= N BB in recent hands).
  - Late in long sessions (after playing >= M hours or >= K hands).

Metrics tracked before and after the tilt/fatigue trigger:
  - Net result (BB/100)
  - VPIP (voluntarily put money in pot %)
  - PFR (pre-flop raise %)
  - Average bet size as fraction of pot
  - Fold-to-continuation-bet frequency

Hands are ordered by clock time extracted from hand-history timestamps,
across all files in the session. Gaps longer than 30 minutes within a
hand-history file are treated as separate sessions.

Output: a text section and a simple ASCII plot of running winnings
        with tilt-trigger points marked.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


DOWNSWING_THRESHOLD_BB = 20.0   # BB lost in a rolling window to trigger tilt flag
SESSION_LENGTH_HOURS   = 3.0    # hours played before fatigue flag
SESSION_LENGTH_HANDS   = 200    # hands played before fatigue flag


@dataclass
class TiltWindow:
    """Stats for a window of hands before or after a tilt trigger."""
    label: str               # "pre-tilt" | "post-tilt" | "pre-fatigue" | "post-fatigue"
    hands: int
    bb_per_100: float
    vpip: float
    pfr: float
    fold_to_cbet: float


@dataclass
class TiltReport:
    """Full tilt and fatigue analysis."""
    downswing_windows: list[TiltWindow] = field(default_factory=list)
    fatigue_windows: list[TiltWindow] = field(default_factory=list)
    ascii_winnings_plot: str = ""


def detect_tilt_windows(
    hands: list[dict[str, Any]],
    downswing_threshold_bb: float = DOWNSWING_THRESHOLD_BB,
) -> list[TiltWindow]:
    """
    Identify pre- and post-downswing windows within sessions.

    Hands must be ordered by clock time. A tilt trigger fires when
    Hero's running P&L drops by downswing_threshold_bb within a session.

    Args:
        hands:                  Hand dicts ordered by timestamp, with
                                'session_id', 'timestamp', 'result_bb' keys.
        downswing_threshold_bb: BB loss in rolling window to trigger flag.

    Returns:
        List of TiltWindow objects with pre/post comparisons.

    Raises:
        NotImplementedError: This function is not yet implemented.
    """
    raise NotImplementedError("planned")


def detect_fatigue_windows(
    hands: list[dict[str, Any]],
    length_hours: float = SESSION_LENGTH_HOURS,
    length_hands: int = SESSION_LENGTH_HANDS,
) -> list[TiltWindow]:
    """
    Identify pre- and post-fatigue windows within long sessions.

    Args:
        hands:         Hand dicts ordered by timestamp.
        length_hours:  Session length threshold in hours.
        length_hands:  Session length threshold in hands.

    Returns:
        List of TiltWindow objects comparing early vs late session play.

    Raises:
        NotImplementedError: This function is not yet implemented.
    """
    raise NotImplementedError("planned")


def build_tilt_report(hands: list[dict[str, Any]]) -> TiltReport:
    """
    Build the full tilt and fatigue report.

    Args:
        hands: All parsed hand dicts with 'timestamp', 'session_id',
               'result_bb', 'vpip', 'pfr', 'fold_to_cbet' keys.

    Returns:
        A TiltReport with downswing and fatigue windows and an ASCII plot.

    Raises:
        NotImplementedError: This function is not yet implemented.
    """
    raise NotImplementedError("planned")
