from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from poker_analyzer.parser import Action, Cashout, PotWin, UncalledBet, parse_file, parse_text

FIXTURE = Path(__file__).parent / "fixtures" / "sample_hands.txt"
RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
D = Decimal


@pytest.fixture(scope="module")
def result():
    return parse_file(FIXTURE)


@pytest.fixture(scope="module")
def hands(result):
    return {h.hand_id: h for h in result.hands}


def test_fixture_parses_cleanly(result):
    assert len(result.hands) == 4
    assert result.failures == []
    assert result.all_unrecognized() == []
    assert [h.warnings for h in result.hands] == [[]] * 4


def test_preflop_fold(hands):
    h = hands["HD149259765"]
    assert h.stakes == "$0.05/$0.1"
    assert h.played_at == datetime(2026, 10, 21, 19, 18, 9)
    assert h.table_name == "NLHRed11"
    assert h.max_seats == 6
    assert h.button_seat == 2
    assert [(s.seat, s.player, s.stack) for s in h.seats][:3] == [
        (1, "388351a0", D("19.05")),
        (2, "ea2286aa", D("12.45")),
        (3, "Hero", D("20.72")),
    ]
    assert h.hero == "Hero"
    assert h.hero_cards == ["2h", "Ad"]
    assert h.actions[0] == Action("preflop", "Hero", "post_sb", D("0.05"))
    assert h.actions[-3:] == [
        Action("preflop", "Hero", "raise", D("0.2"), D("0.3")),
        Action("preflop", "1b9878e9", "raise", D("0.7"), D("1")),
        Action("preflop", "Hero", "fold"),
    ]
    assert h.board == []
    assert h.shown_cards == {}
    assert h.uncalled_bets == [UncalledBet("1b9878e9", D("0.7"))]
    assert h.collected == [PotWin("1b9878e9", D("0.57"))]
    assert (h.total_pot, h.rake) == (D("0.6"), D("0.03"))
    hero_result = next(r for r in h.results if r.player == "Hero")
    assert (hero_result.positions, hero_result.outcome, hero_result.fold_street) == (
        ["small blind"],
        "folded",
        "preflop",
    )


def test_river_showdown_split_pot(hands):
    h = hands["HD149259563"]
    assert h.board == ["5d", "6d", "4s", "Jh", "8s"]
    assert [a.street for a in h.actions].count("river") == 4
    assert h.actions[-1] == Action("river", "1b9878e9", "call", D("3.28"))
    assert h.shown_cards == {"388351a0": ["7h", "8h"], "1b9878e9": ["7s", "7c"]}
    assert h.collected == [PotWin("388351a0", D("7.36")), PotWin("1b9878e9", D("7.36"))]
    assert h.rake == D("0.76")
    assert h.fees["Jackpot"] == D("0.1")
    winner = next(r for r in h.results if r.player == "388351a0")
    assert winner.outcome == "showed_won"
    assert winner.description == "a straight, Eight to Four"


def test_preflop_all_in(hands):
    h = hands["HD149259722"]
    assert h.actions[-2:] == [
        Action("preflop", "52764000", "raise", D("18.6"), D("19.36"), all_in=True),
        Action("preflop", "388351a0", "call", D("9.24"), all_in=True),
    ]
    assert h.uncalled_bets == [UncalledBet("52764000", D("9.36"))]
    # Cards are shown before the board runs out.
    assert h.shown_cards == {"52764000": ["Ac", "Kh"], "388351a0": ["Ks", "Kd"]}
    assert h.board == ["6d", "8s", "Td", "4h", "3h"]
    assert h.committed() == {
        "ea2286aa": D("0.05"),
        "Hero": D("0.1"),
        "52764000": D("19.36"),
        "388351a0": D("10"),
    }
    loser = next(r for r in h.results if r.player == "52764000")
    assert (loser.outcome, loser.cards, loser.description) == ("showed_lost", ["Ac", "Kh"], "Ace high")


def test_all_in_with_side_pot(hands):
    h = hands["HD149258486"]
    assert h.hero_cards == ["Qs", "Qc"]
    assert Action("preflop", "d341f2e1", "call", D("1.32"), all_in=True) in h.actions
    # Main pot and side pot are separate "collected" lines with no labels.
    assert h.collected == [PotWin("Hero", D("4.99")), PotWin("Hero", D("3.35"))]
    hero_result = next(r for r in h.results if r.player == "Hero")
    assert hero_result.amount == D("8.34")
    assert hero_result.positions == ["button"]


def test_unrecognized_lines_are_reported():
    text = FIXTURE.read_text(encoding="utf-8").split("\n\n\n")[0]
    text = text.replace("b42a3763: folds\n", "b42a3763: folds\nb42a3763: straddles $0.2\nsomething odd\n", 1)
    result = parse_text(text)
    assert len(result.hands) == 1
    assert [u.text for u in result.all_unrecognized()] == ["b42a3763: straddles $0.2", "something odd"]
    assert result.all_unrecognized()[0].line_no == 19


def test_lines_outside_hands_are_reported():
    result = parse_text("garbage before\n\n" + FIXTURE.read_text(encoding="utf-8"))
    assert [(u.line_no, u.text) for u in result.unrecognized] == [(1, "garbage before")]


def test_bad_header_is_a_failure_not_a_crash():
    text = FIXTURE.read_text(encoding="utf-8").replace("Hold'em No Limit ($0.05/$0.1) - 2026/10/21 19:18:09", "???", 1)
    result = parse_text(text)
    assert len(result.hands) == 3
    assert len(result.failures) == 1
    assert "unrecognized header" in result.failures[0].error


def test_misread_amount_triggers_warning():
    text = FIXTURE.read_text(encoding="utf-8").split("\n\n\n")[0].replace("collected $0.57", "collected $0.75")
    (hand,) = parse_text(text).hands
    assert any("total pot" in w for w in hand.warnings)


def fixture_hand(file_name, hand_id):
    result = parse_file(Path(__file__).parent / "fixtures" / file_name)
    assert result.all_unrecognized() == []
    hand = next(h for h in result.hands if h.hand_id == hand_id)
    assert hand.warnings == []
    return hand


def test_run_it_twice():
    h = fixture_hand("GG20260902-0500 - NLHRed13 - 0.05 - 0.1 - 6max.txt", "HD142177979")
    assert h.run_count == 2
    assert h.boards == [["8h", "Tc", "6c", "7s", "4h"], ["Qc", "3s", "9s", "4c", "3c"]]
    assert h.collected == [PotWin("67345e37", D("4.44"), 1), PotWin("67345e37", D("4.43"), 2)]
    winner = next(r for r in h.results if r.player == "67345e37")
    assert (winner.outcome, winner.amount) == ("showed_won", D("8.87"))
    assert [(r.won, r.amount, r.description) for r in winner.runs] == [
        (True, D("4.44"), "a straight, Ten to Six"),
        (True, D("4.43"), "a full house, Nines full of Threes"),
    ]


def test_run_three_times_from_the_river():
    h = fixture_hand("GG20260903-2100 - NLHRed16 - 0.05 - 0.1 - 6max.txt", "HD142412546")
    assert h.run_count == 3
    assert [b[-1] for b in h.boards] == ["7s", "8s", "8d"]
    assert h.boards[1][:4] == h.boards[0][:4]
    # Every street is labelled FIRST, but the betting still lands on the right street.
    assert [a.street for a in h.actions if a.action == "bet"] == ["flop", "turn"]
    loser = next(r for r in h.results if r.player == "3ffcf39c")
    assert [r.won for r in loser.runs] == [False, False, False]


def test_straddles_and_dead_blinds():
    h = fixture_hand("GG20260917-0331 - NLHRed2 - 0.05 - 0.1 - 6max.txt", "HD144262027")
    assert [(a.action, a.raise_to) for a in h.actions if a.player == "328eb02c"] == [
        ("straddle", D("0.2")), ("straddle", D("0.4")), ("straddle", D("0.8")), ("straddle", D("1.6")),
    ]
    assert h.committed()["328eb02c"] == D("1.6")
    h = fixture_hand("GG20260902-0500 - NLHRed13 - 0.05 - 0.1 - 6max.txt", "HD142176975")
    assert Action("preflop", "4df181ab", "post_dead", D("0.05")) in h.actions
    assert h.committed()["4df181ab"] == D("0.15")


def test_ev_cashout_and_time_bank():
    h = fixture_hand("GG20260906-0504 - NLHPurple9 - 0.1 - 0.25 - 6max.txt", "HD142742656")
    assert h.cashouts["f7d21c5a"] == Cashout(chose=True, received=D("6.78"))
    assert next(r for r in h.results if r.player == "f7d21c5a").cashout_received == D("14.04")
    h = fixture_hand("GG20260902-0500 - NLHRed13 - 0.05 - 0.1 - 6max.txt", "HD142177755")
    assert h.cashouts["711c6b1b"] == Cashout(chose=True, risk_paid=D("5.24"))
    h = fixture_hand("GG20260903-1429 - NLHRed8 - 0.05 - 0.1 - 6max.txt", "HD142373187")
    assert {r.player: r.time_bank for r in h.results}["Hero"] == D("-0.1")
    assert sum(r.time_bank for r in h.results) == 0


@pytest.mark.skipif(not any(RAW_DIR.glob("*.txt")), reason="no hand histories in data/raw")
def test_all_raw_files_parse_cleanly():
    for path in RAW_DIR.glob("*.txt"):
        result = parse_file(path)
        assert result.hands, path
        assert result.failures == [], path
        assert result.all_unrecognized() == [], path
        assert [(h.hand_id, h.warnings) for h in result.hands if h.warnings] == [], path
