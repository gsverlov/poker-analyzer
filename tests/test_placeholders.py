"""
Smoke tests: verify that every placeholder module imports without error.
These tests do NOT call any placeholder functions; they only check that
the modules load, so the test suite stays green until each part is built.
"""
import importlib
import pytest


PLACEHOLDER_MODULES = [
    "poker_analyzer.board_texture",
    "poker_analyzer.hand_strength",
    "poker_analyzer.postflop_labels",
    "poker_analyzer.postflop_report",
    "poker_analyzer.ml",
    "poker_analyzer.ml.features",
    "poker_analyzer.ml.model",
    "poker_analyzer.ml.bluff_ev",
    "poker_analyzer.stats",
    "poker_analyzer.holdout",
    "poker_analyzer.leak_report",
    "poker_analyzer.tilt",
]


@pytest.mark.parametrize("module_name", PLACEHOLDER_MODULES)
def test_placeholder_imports(module_name: str) -> None:
    """Each placeholder module must import cleanly."""
    mod = importlib.import_module(module_name)
    assert mod is not None
