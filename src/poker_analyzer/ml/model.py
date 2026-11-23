# PLACEHOLDER - not implemented yet
"""
Logistic regression baseline and LightGBM opponent model (Part 4).

Training protocol:
  - Date-based train/test split: oldest sessions -> train, newest -> test.
    Default split: oldest 70% of session-dates = train.
  - Models are fit only on postflop facing-a-bet rows.
  - Evaluation metrics: log loss and calibration (reliability diagram).

Outputs:
  - Trained model objects (serialisable with joblib).
  - Out-of-fold fold/call/raise probability predictions for every row,
    used by bluff_ev.py to score Hero's decisions.

Planned dependencies (not yet in requirements.txt):
  scikit-learn >= 1.4
  lightgbm >= 4.0
"""
from __future__ import annotations
from typing import Any
import numpy as np  # type: ignore


def train_logistic_baseline(
    X_train: "np.ndarray",
    y_train: "np.ndarray",
) -> Any:
    """
    Fit a multinomial logistic regression baseline model.

    Args:
        X_train: Feature matrix (n_samples, n_features), float32.
        y_train: Label array (n_samples,), int in {0, 1, 2}.

    Returns:
        Fitted sklearn LogisticRegression model object.

    Raises:
        NotImplementedError: This function is not yet implemented.
    """
    raise NotImplementedError("planned")


def train_lightgbm(
    X_train: "np.ndarray",
    y_train: "np.ndarray",
    X_val: "np.ndarray",
    y_val: "np.ndarray",
) -> Any:
    """
    Fit a LightGBM multiclass classifier with early stopping.

    Args:
        X_train: Training features.
        y_train: Training labels.
        X_val:   Validation features (used for early stopping).
        y_val:   Validation labels.

    Returns:
        Fitted LightGBM Booster object.

    Raises:
        NotImplementedError: This function is not yet implemented.
    """
    raise NotImplementedError("planned")


def evaluate_model(
    model: Any,
    X_test: "np.ndarray",
    y_test: "np.ndarray",
) -> dict[str, float]:
    """
    Evaluate a trained model on a held-out test set.

    Args:
        model: A fitted classifier with a predict_proba() method.
        X_test: Test feature matrix.
        y_test: True labels.

    Returns:
        Dictionary with keys: 'log_loss', 'brier_score', 'accuracy'.

    Raises:
        NotImplementedError: This function is not yet implemented.
    """
    raise NotImplementedError("planned")


def date_based_split(
    decisions: list[dict[str, Any]],
    train_fraction: float = 0.7,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Split decisions into train/test sets by session date.

    The oldest train_fraction of unique session dates go to train;
    the newest (1 - train_fraction) go to test. Never shuffles,
    so no data leakage across time.

    Args:
        decisions: List of decision dicts, each with a 'session_date' key.
        train_fraction: Fraction of session dates assigned to train (default 0.7).

    Returns:
        Tuple (train_decisions, test_decisions).

    Raises:
        NotImplementedError: This function is not yet implemented.
    """
    raise NotImplementedError("planned")
