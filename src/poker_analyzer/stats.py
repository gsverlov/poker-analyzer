# PLACEHOLDER - not implemented yet
"""
Shrinkage estimation and bootstrap-by-session utilities (shared, Part 5).

Shrinkage
  Shrinks a spot's observed metric (e.g. BB/100 in a given spot) toward
  the population mean for the broader group it belongs to (e.g. all river
  calls, or all c-bet spots). The weight is determined by the sample size
  relative to a prior strength hyperparameter.

  shrunk = (n * observed + k * group_mean) / (n + k)

  where k is the prior strength (default: equivalent to 50 hands).

Bootstrap by session
  Resamples whole sessions (with replacement) rather than individual hands
  to preserve within-session autocorrelation. Each bootstrap replicate:
    1. Resamples sessions from the full session list.
    2. Recomputes all shrinkage estimates using those sessions' hands.
  Returns the distribution of estimates across replicates.
"""
from __future__ import annotations
from typing import Any
import numpy as np  # type: ignore


def shrink_toward_group(
    observed: float,
    sample_size: int,
    group_mean: float,
    prior_strength: float = 50.0,
) -> float:
    """
    Apply James-Stein-style shrinkage of an observed metric.

    Args:
        observed:       Raw observed metric (e.g. BB/100 in this spot).
        sample_size:    Number of hands in this spot.
        group_mean:     Population mean for the broader group.
        prior_strength: Equivalent prior sample size (default 50 hands).

    Returns:
        Shrunk estimate, pulled toward group_mean by prior_strength.

    Raises:
        NotImplementedError: This function is not yet implemented.
    """
    raise NotImplementedError("planned")


def bootstrap_by_session(
    hands: list[dict[str, Any]],
    stat_fn: Any,
    n_replicates: int = 1000,
    seed: int = 42,
) -> np.ndarray:
    """
    Bootstrap confidence interval by resampling whole sessions.

    Args:
        hands:        List of parsed hand dicts, each with a 'session_id' key.
        stat_fn:      Callable that takes a list of hands and returns a float
                      (or dict of floats). Called once per replicate.
        n_replicates: Number of bootstrap replicates (default 1000).
        seed:         Random seed for reproducibility.

    Returns:
        Array of shape (n_replicates,) containing stat_fn output per replicate.
        If stat_fn returns a dict, returns an array of dicts.

    Raises:
        NotImplementedError: This function is not yet implemented.
    """
    raise NotImplementedError("planned")
