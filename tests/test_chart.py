from dataclasses import replace
from pathlib import Path

import pytest

from poker_analyzer import db
from poker_analyzer.chart import (
    Compared, Group, action_stats, chart_action, chart_spot, compare, leak, load_charts, true_bucket,
)
from poker_analyzer.importer import import_folder
from poker_analyzer.preflop import Decision, hand_group, hero_decisions

FIXTURES = Path(__file__).parent / "fixtures" / "chart"


@pytest.fixture(scope="module")
def charts():
    return load_charts()


@pytest.fixture(scope="module")
def decisions(tmp_path_factory):
    conn = db.connect(tmp_path_factory.mktemp("db") / "test.db")
    report = import_folder(conn, FIXTURES)
    assert report.failures == [] and report.hands_imported == 7
    ds = hero_decisions(conn)
    conn.close()
    return ds


def hero_decision(ds, hand_id, n=0):
    """Hero's n-th decision in the hand."""
    return [d for d in ds.decisions if d.hand_id == hand_id][n]


def decision(**changes) -> Decision:
    base = Decision(
        hand_id="x", situation="rfi", hero_position="UTG", villain_position=None, hole_cards="Ah Kh", hand="AKs",
        group=hand_group("AKs"), action="raise", hero_all_in=False, raise_to_bb=2.5, faced_bb=None, limpers=0,
        callers=0, result_bb=0.0, all_in_ev=False, players=6, hero_stack_bb=100.0, max_other_stack_bb=100.0,
    )
    return replace(base, **changes)


@pytest.mark.parametrize(
    "hand_id, n, players, spot, action",
    [
        ("HD142209912", 0, 5, ("rfi", "HJ"), "raise"),  # 5-handed: the first seat is HJ
        ("HD142230757", 0, 4, ("vs_open", "BB", "CO"), "3bet"),  # 4-handed: CO opens first in
        ("HD142500181", 0, 3, ("vs_open", "SB", "BTN"), "fold"),  # 3-handed: the button opens
        ("HD142410900", 1, 6, ("vs_3bet", "UTG", "HJ"), "call"),  # Hero opens UTG, HJ 3-bets
        ("HD142230276", 1, 6, ("vs_3bet", "CO", "BB"), "call"),  # Hero opens CO, BB 3-bets
    ],
)
def test_positions_and_opener_map_to_the_chart(decisions, charts, hand_id, n, players, spot, action):
    d = hero_decision(decisions, hand_id, n)
    assert d.players == players
    assert chart_spot(d, charts) == (spot, None, None)
    assert chart_action(spot[0], d) == action


def test_heads_up_is_not_compared(decisions, charts):
    d = hero_decision(decisions, "HD142378965")
    assert (d.players, d.situation) == (2, "vs_open")
    assert chart_spot(d, charts) == (None, "heads-up", None)


def test_hand_missing_from_the_chart_always_folds(charts):
    assert "72o" not in charts.spots[("rfi", "UTG")]
    assert charts.freqs(("rfi", "UTG"), "72o") == {"raise": 0.0, "call": 0.0, "fold": 1.0}
    assert charts.freqs(("rfi", "UTG"), "66") == pytest.approx({"raise": 0.409, "call": 0.0, "fold": 0.591})
    # A few rows add up to 100.1% from rounding; they are scaled back to 100%.
    assert sum(charts.freqs(("vs_open", "BTN", "UTG"), "AQs").values()) == pytest.approx(1.0)
    assert charts.freqs(("vs_open", "BTN", "UTG"), "AQs")["fold"] == 0


def make(action, open_freq):
    """A UTG RFI decision where the chart opens the hand open_freq of the time."""
    return Compared(None, ("rfi", "UTG"), action, {"raise": open_freq, "call": 0.0, "fold": 1 - open_freq})


def test_expected_variance_and_z():
    # The chart opens these hands 50%, 20%, 100% and 10% of the time; Hero opened the first three and folded the last.
    items = [make("raise", 0.5), make("raise", 0.2), make("raise", 1.0), make("fold", 0.1)]
    s = action_stats(items, "raise")
    assert s.expected == pytest.approx(1.8)
    assert s.actual == 3
    assert s.variance == pytest.approx(0.25 + 0.16 + 0 + 0.09)
    assert s.z == pytest.approx(1.2 / 0.5 ** 0.5)  # 1.70
    assert not s.flagged(min_n=4)
    folds = action_stats(items, "fold")
    assert (folds.expected, folds.actual) == (pytest.approx(2.2), 1)
    assert all(c.in_line for c in items)  # 20% is at least 10%, and the fold comes 90% of the time
    assert not make("raise", 0.05).in_line


def test_deviation_in_a_pure_spot_is_flagged():
    # The chart always opens these hands; Hero folded one of 12.
    items = [make("raise", 1.0) for _ in range(11)] + [make("fold", 1.0)]
    s = action_stats(items, "raise")
    assert s.variance == 0 and s.z is None
    assert s.flagged()
    g = Group((("rfi", "UTG"), None), "group", "Suited broadways", items)
    assert g.flagged == ["raise", "fold"]
    lk = leak(g, hands_dealt=1000)
    assert lk.kind == "too tight" and lk.per_1000 == pytest.approx(-1.0)
    assert lk.sentence == (
        "UTG open, too tight: you open suited broadways only 92% of the time vs 100% for the chart "
        "(1.0 fewer opens per 1,000 hands)."
    )
    # No difference, or too few decisions, is not flagged.
    assert not action_stats(items[:11], "raise").flagged()
    assert action_stats(items[2:], "raise").flagged()  # 10 decisions are enough
    assert not action_stats(items[3:], "raise").flagged()  # 9 are not


def test_three_bet_with_a_hand_outside_the_opening_range_is_not_scored(decisions, charts):
    d = hero_decision(decisions, "HD149173672", 1)
    assert (d.situation, d.hero_position, d.villain_position, d.hand, d.action) == ("vs_3bet", "HJ", "BTN", "J7s", "call")
    assert charts.freqs(("rfi", "HJ"), "J7s")["raise"] == 0
    result = compare(decisions, charts)
    assert [c.decision.hand_id for c in result.off_chart_open] == ["HD149173672"]
    assert "HD149173672" not in {c.decision.hand_id for c in result.compared if c.spot[0] == "vs_3bet"}
    # The open itself is still scored, as an off-chart RFI.
    (rfi,) = [c for c in result.compared if c.decision.hand_id == "HD149173672"]
    assert rfi.spot == ("rfi", "HJ") and not rfi.in_line


def test_raise_facing_a_3bet_is_a_4bet_or_an_all_in():
    d = decision(situation="vs_3bet", villain_position="BTN", villain_stack_bb=100.0, raise_to_bb=22.0)
    assert chart_action("vs_3bet", d) == "4bet"
    assert chart_action("vs_3bet", replace(d, raise_to_bb=55.0)) == "allin"  # more than half of 100bb
    assert chart_action("vs_3bet", replace(d, hero_all_in=True)) == "allin"
    assert chart_action("rfi", decision(action="call")) == "call"  # a limp


@pytest.mark.parametrize(
    "changes, reason",
    [
        ({"hero_stack_bb": 200.0, "max_other_stack_bb": 170.0}, "stack outside 60-150bb"),
        ({"max_other_stack_bb": 40.0}, "stack outside 60-150bb"),  # RFI: vs the biggest other stack
        ({"situation": "squeeze"}, "squeeze"),
        ({"situation": "vs_limpers"}, "limpers"),
        ({"situation": "vs_4bet"}, "facing a 4-bet"),
        ({"situation": "other", "other_kind": "facing a 3-bet without having acted"}, "other"),
    ],
)
def test_decisions_that_are_not_compared(charts, changes, reason):
    assert chart_spot(decision(**changes), charts)[1] == reason
    assert chart_spot(decision(hero_stack_bb=200.0, max_other_stack_bb=120.0), charts)[0] == ("rfi", "UTG")


def test_true_open_size_bucket():
    assert true_bucket(("vs_open", "BB", "BTN")) == "small (2.1-2.9bb)"
    assert true_bucket(("vs_open", "BB", "SB")) == "3bb"
