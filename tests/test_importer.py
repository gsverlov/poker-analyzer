import re
import shutil
from pathlib import Path

import pytest

from poker_analyzer import db
from poker_analyzer.importer import import_folder

FIXTURES = Path(__file__).parent / "fixtures"
RED13 = "GG20260902-0500 - NLHRed13 - 0.05 - 0.1 - 6max.txt"
RED1 = "GG20260903-1918 - NLHRed1 - 0.05 - 0.1 - 6max.txt"

ACTION_LINE = re.compile(r"^[^:\n]+: (posts|straddle|folds|checks|calls|bets|raises)", re.M)
SEAT_LINE = re.compile(r"^Seat \d+: (\S+) \(\$[\d.]+ in chips\)", re.M)


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture
def report(conn):
    return import_folder(conn, FIXTURES)


def rows(conn, sql, *params):
    return [tuple(r) for r in conn.execute(sql, params)]


def test_imports_every_fixture_hand(conn, report):
    files = sorted(FIXTURES.glob("*.txt"))
    texts = [f.read_text(encoding="utf-8") for f in files]
    assert report.failures == []
    assert report.unrecognized == []
    assert report.hands_imported == sum(t.count("Poker Hand #") for t in texts)
    # Counted straight from the text, independently of the parser.
    assert db.row_counts(conn) == {
        "sessions": len(files),
        "hands": report.hands_imported,
        "players": sum(len(set(SEAT_LINE.findall(t))) for t in texts),
        "seats": sum(len(SEAT_LINE.findall(t)) for t in texts),
        "actions": sum(len(ACTION_LINE.findall(t)) for t in texts),
    }


def test_money_adds_up_to_the_cent(conn, report):
    hands = conn.execute(
        "SELECT h.hand_id, h.total_pot_cents, h.rake_cents + h.jackpot_cents + h.bingo_cents + h.fortune_cents"
        " + h.tax_cents AS fees, SUM(s.invested_cents) AS invested, SUM(s.collected_cents) AS collected,"
        " SUM(s.net_cents) AS net, MAX(s.invested_cents - s.stack_cents) AS overspend"
        " FROM hands h JOIN seats s USING (hand_id) GROUP BY h.hand_id"
    ).fetchall()
    assert len(hands) == 16
    for h in hands:
        assert h["invested"] == h["total_pot_cents"], h["hand_id"]
        assert h["collected"] + h["fees"] == h["total_pot_cents"], h["hand_id"]
        assert h["net"] + h["fees"] == 0, h["hand_id"]
        assert h["overspend"] <= 0, h["hand_id"]
    # Time bank card money moves outside the pot and nets to zero across the table.
    assert rows(conn, "SELECT SUM(time_bank_cents) FROM seats WHERE hand_id = 'HD142373187'") == [(0,)]


def test_hand_details(conn, report):
    assert rows(
        conn,
        "SELECT hand_id, session_order, played_at, time_zone FROM hands JOIN sessions ON sessions.id = session_id"
        " WHERE file_name = ? ORDER BY session_order",
        RED13,
    ) == [
        ("HD142176718", 1, "2026/09/02 01:28:52", "America/New_York"),
        ("HD142176975", 2, "2026/09/02 01:39:55", "America/New_York"),
        ("HD142177755", 3, "2026/09/02 02:14:48", "America/New_York"),
        ("HD142177979", 4, "2026/09/02 02:24:51", "America/New_York"),
    ]
    assert rows(conn, "SELECT table_name, small_blind_cents, big_blind_cents FROM sessions WHERE file_name = ?", RED13) == [
        ("NLHRed13", 5, 10)
    ]
    # Run it twice: both boards, and the winner's two collections add up.
    assert rows(conn, "SELECT run_count, board, board_run2 FROM hands WHERE hand_id = 'HD142177979'") == [
        (2, "8h Tc 6c 7s 4h", "Qc 3s 9s 4c 3c")
    ]
    assert rows(conn, "SELECT board_run2, board_run3 FROM hands WHERE hand_id = 'HD142412546'") == [
        ("4h 6d 4d Th 8s", "4h 6d 4d Th 8d")
    ]
    assert rows(
        conn,
        "SELECT hh_id, collected_cents, net_cents, hole_cards, showed FROM seats JOIN players ON players.id = player_id"
        " WHERE hand_id = 'HD142177979' AND collected_cents > 0",
    ) == [("67345e37", 887, 433, "9c 9h", 1)]
    # Hero's cards are stored even when not shown.
    assert rows(
        conn,
        "SELECT hole_cards, showed FROM seats JOIN players ON players.id = player_id"
        " WHERE hand_id = 'HD142177979' AND is_hero",
    ) == [("Ad Js", 0)]
    # EV Cashout: collected half the pot, plus a payment from outside it.
    assert rows(
        conn,
        "SELECT cashout_chosen, collected_cents, cashout_received_cents, cashout_risk_cents FROM seats"
        " JOIN players ON players.id = player_id WHERE hand_id = 'HD142742656' AND hh_id = 'f7d21c5a'",
    ) == [(1, 726, 678, None)]
    assert rows(conn, "SELECT cashout_risk_cents FROM seats WHERE hand_id = 'HD142177755' AND cashout_chosen") == [(524,)]


def test_blinds_straddles_and_pot_before(conn, report):
    assert rows(
        conn,
        "SELECT action, amount_cents, raise_to_cents, pot_before_cents FROM actions"
        " WHERE hand_id = 'HD144262027' AND seq <= 6 ORDER BY seq",
    ) == [
        ("post_sb", 5, None, 0),
        ("post_bb", 10, None, 5),
        ("straddle", 20, 20, 15),
        ("straddle", 40, 40, 35),
        ("straddle", 80, 80, 55),
        ("straddle", 160, 160, 95),
    ]
    # A missed blind is dead money: it goes in the pot but the player can still check their big blind.
    assert rows(
        conn,
        "SELECT action, amount_cents, pot_before_cents FROM actions JOIN players ON players.id = player_id"
        " WHERE hand_id = 'HD142176975' AND hh_id = '4df181ab' ORDER BY seq",
    ) == [("post_dead", 5, 15), ("post_bb", 10, 20), ("check", None, 30), ("fold", None, 80)]


def test_positions_with_fewer_than_six_players(conn, report):
    def positions(hand_id):
        return rows(
            conn,
            "SELECT seat_no, hh_id, position FROM seats JOIN players ON players.id = player_id"
            " WHERE hand_id = ? ORDER BY seat_no",
            hand_id,
        )

    assert positions("HD142412688") == [  # 5 players, button seat 5
        (1, "Hero", "BB"), (2, "2c97060e", "HJ"), (4, "4e1631b2", "CO"), (5, "fb1dab44", "BTN"), (6, "e3c4f032", "SB"),
    ]
    assert positions("HD142411766") == [  # 4 players, button seat 2
        (1, "Hero", "CO"), (2, "2c97060e", "BTN"), (3, "2bfac217", "SB"), (4, "4e1631b2", "BB"),
    ]
    assert positions("HD142411259") == [  # 3 players, button seat 5
        (1, "Hero", "BB"), (5, "75961f1b", "BTN"), (6, "e3c4f032", "SB"),
    ]
    assert positions("HD142379059") == [(1, "Hero", "BTN/SB"), (4, "b925518c", "BB")]  # heads-up
    six = positions("HD149259765")  # 6 players, button seat 2
    assert [p for _, _, p in six] == ["CO", "BTN", "SB", "BB", "UTG", "HJ"]


def test_players_are_per_session_with_hero_flagged(conn, report):
    assert rows(conn, "SELECT COUNT(*) FROM players WHERE hh_id = 'Hero' AND is_hero") == [(7,)]
    assert rows(conn, "SELECT COUNT(*) FROM players WHERE is_hero AND hh_id != 'Hero'") == [(0,)]
    # e3c4f032 plays several hands in one file but is one player row in that session.
    assert rows(conn, "SELECT COUNT(*) FROM players WHERE hh_id = 'e3c4f032'") == [(1,)]


def test_reimport_adds_nothing(conn, report, tmp_path):
    before = db.row_counts(conn)
    again = import_folder(conn, FIXTURES)
    assert (again.files_skipped, again.hands_imported, again.failures) == (len(list(FIXTURES.glob("*.txt"))), 0, [])
    assert db.row_counts(conn) == before

    # A renamed copy of an imported file is read, but every hand is already there.
    copies = tmp_path / "copies"
    copies.mkdir()
    shutil.copy(FIXTURES / RED13, copies / "renamed.txt")
    third = import_folder(conn, copies)
    assert (third.hands_imported, third.hands_already_present) == (0, 4)
    assert db.row_counts(conn) == before


def test_failed_hands_are_reported_and_retried(conn, tmp_path):
    folder = tmp_path / "raw"
    folder.mkdir()
    good = (FIXTURES / RED1).read_text(encoding="utf-8")
    broken = good.replace("Hero: folds\n", "Hero: folds\nHero: does something new\n", 1)
    assert broken != good
    (folder / RED1).write_text(broken, encoding="utf-8")

    first = import_folder(conn, folder)
    assert [u.text for _, u in first.unrecognized] == ["Hero: does something new"]
    assert len(first.failures) == 1
    failure = first.failures[0]
    assert failure.hand_id == "HD142412688"
    assert "unrecognized" in failure.reason and "Hero: does something new" in failure.reason
    assert first.hands_imported == 3
    assert rows(conn, "SELECT complete FROM sessions") == [(0,)]

    # Incomplete files are re-read every run and still report the problem, without duplicating hands.
    second = import_folder(conn, folder)
    assert (second.files_skipped, second.hands_imported, second.hands_already_present) == (0, 0, 3)
    assert len(second.failures) == 1

    # Once the hand can be read, it is imported and the file is marked complete.
    (folder / RED1).write_text(good, encoding="utf-8")
    third = import_folder(conn, folder)
    assert (third.hands_imported, third.failures) == (1, [])
    assert rows(conn, "SELECT complete FROM sessions") == [(1,)]
    assert rows(conn, "SELECT session_order FROM hands WHERE hand_id = 'HD142412688'") == [(4,)]
