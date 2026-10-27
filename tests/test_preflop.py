from pathlib import Path

import pytest

from poker_analyzer import db
from poker_analyzer.equity import cards, equity
from poker_analyzer.importer import import_folder
from poker_analyzer.preflop import hand_class, hand_group, hero_decisions

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def decisions(tmp_path_factory):
    conn = db.connect(tmp_path_factory.mktemp("db") / "test.db")
    report = import_folder(conn, FIXTURES / "preflop")
    assert report.failures == [] and report.hands_imported == 4
    result = hero_decisions(conn)
    conn.close()
    return result


def only(ds, hand_id):
    return [d for d in ds.decisions if d.hand_id == hand_id]


def test_bb_fold_is_zero(decisions):
    (d,) = only(decisions, "HD142232018")
    assert (d.situation, d.hero_position, d.villain_position, d.action) == ("vs_open", "BB", "BTN", "fold")
    assert d.faced_bb == 2.0 and d.size_bucket == "min-raise (2bb)"
    assert d.result_bb == 0  # the posted big blind is not counted


def test_bb_call_that_loses_counts_only_the_call(decisions):
    # BB calls a 2bb open ($0.10 more), then check-folds the flop.
    (d,) = only(decisions, "HD142235271")
    assert (d.situation, d.action, d.hand, d.group) == ("vs_open", "call", "A4o", "Offsuit aces (A2o-A9o)")
    assert d.result_bb == pytest.approx(-1.0)
    assert not d.all_in_ev


def test_all_in_uses_equity_not_the_actual_result(decisions):
    # Hero's QQ gets it in preflop against KK and wins the hand, but is credited with QQ's equity.
    ds = only(decisions, "HD142234313")
    assert [(d.situation, d.action) for d in ds] == [("rfi", "raise"), ("vs_3bet", "raise"), ("other", "call")]
    assert all(d.all_in_ev for d in ds)
    qq = equity([cards("Qc Qs"), cards("Kc Ks")])[0]
    assert 0.17 < qq < 0.19
    pot_after_fees = 21.25 - 1.00 - 0.10  # total pot minus rake and jackpot
    take = qq * pot_after_fees / 0.1
    # Hero invested $10.55 in all: $0.30 open, then $1.58 more as a 4-bet, then $8.67 calling the shove.
    assert [d.result_bb for d in ds] == pytest.approx([take - 105.5, take - 102.5, take - 86.7])
    assert (ds[0].hero_position, ds[1].villain_position) == ("UTG", "CO")  # button is seat 2, 3-bettor seat 1
    assert ds[1].faced_bb == pytest.approx(9.0)
    assert ds[2].other_kind == "facing 1 re-raise(s) after 4-betting"
    assert decisions.all_in_hands == 1


def test_squeeze_spot(decisions):
    (d,) = only(decisions, "HD142231679")
    assert (d.situation, d.hero_position, d.villain_position, d.callers, d.faced_bb) == ("squeeze", "BB", "CO", 1, 2.5)
    assert d.result_bb == 0


def test_straddle_hands_are_left_out(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    import_folder(conn, FIXTURES)  # the importer fixtures include a hand with four straddles
    ds = hero_decisions(conn)
    assert ds.excluded["straddle in the hand"] == 1
    assert "HD144262027" not in {d.hand_id for d in ds.decisions}


@pytest.mark.parametrize(
    "cards_, hand, group",
    [
        ("Ah As", "AA", "Big pairs (QQ+)"),
        ("Qd Qc", "QQ", "Big pairs (QQ+)"),
        ("Jd Jc", "JJ", "Medium pairs (77-JJ)"),
        ("7d 7c", "77", "Medium pairs (77-JJ)"),
        ("6d 6c", "66", "Small pairs (22-66)"),
        ("Ts Ks", "KTs", "Suited broadways"),
        ("5h Ah", "A5s", "Suited wheel aces (A2s-A5s)"),
        ("Ad 6d", "A6s", "Other suited aces (A6s-A9s)"),
        ("Ac 9c", "A9s", "Other suited aces (A6s-A9s)"),
        ("5c 4c", "54s", "Suited connectors (54s-T9s)"),
        ("Tc 9c", "T9s", "Suited connectors (54s-T9s)"),
        ("5c 3c", "53s", "Suited one-gappers (53s-J9s)"),
        ("Jc 9c", "J9s", "Suited one-gappers (53s-J9s)"),
        ("Qc Tc", "QTs", "Suited broadways"),
        ("4c 3c", "43s", "Other suited"),
        ("Kc 9c", "K9s", "Other suited"),
        ("Qd 9c", "Q9o", "Other offsuit"),
        ("Jd Ac", "AJo", "Offsuit broadways"),
        ("2d Ac", "A2o", "Offsuit aces (A2o-A9o)"),
        ("7d 2c", "72o", "Other offsuit"),
    ],
)
def test_hand_groups(cards_, hand, group):
    assert hand_class(cards_) == hand
    assert hand_group(hand) == group
