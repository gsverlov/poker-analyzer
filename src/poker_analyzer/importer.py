"""Bulk-import GGPoker hand history files into the SQLite database.

    python -m poker_analyzer.importer [folder] [--db PATH]

Re-running is safe: files already fully imported are skipped, and a hand already
in the database is never inserted again. A hand with unrecognized lines or failed
consistency checks is not imported; it is listed in the report with the reason,
and the file is retried on the next run so the hand gets in once the parser
handles it.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from . import db, settings
from .parser import PARSER_VERSION, Hand, UnrecognizedLine, parse_text

FEE_COLUMNS = {"Jackpot": "jackpot_cents", "Bingo": "bingo_cents", "Fortune": "fortune_cents", "Tax": "tax_cents"}


@dataclass
class HandFailure:
    file_name: str
    line_no: int
    hand_id: str | None
    reason: str


@dataclass
class ImportReport:
    files_found: int = 0
    files_skipped: int = 0  # already fully imported and unchanged
    hands_imported: int = 0
    hands_already_present: int = 0
    failures: list[HandFailure] = field(default_factory=list)
    unrecognized: list[tuple[str, UnrecognizedLine]] = field(default_factory=list)

    @property
    def files_read(self) -> int:
        return self.files_found - self.files_skipped


def cents(amount: Decimal | None) -> int | None:
    if amount is None:
        return None
    value = amount * 100
    if value != value.to_integral_value():
        raise ValueError(f"{amount} is not a whole number of cents")
    return int(value)


def _cards(cards: list[str] | None) -> str | None:
    return " ".join(cards) if cards else None


def import_folder(conn: sqlite3.Connection, folder: str | Path, time_zone: str = settings.HAND_HISTORY_TIMEZONE) -> ImportReport:
    report = ImportReport()
    for path in sorted(Path(folder).glob("*.txt")):
        report.files_found += 1
        import_file(conn, path, report, time_zone)
    return report


def import_file(conn: sqlite3.Connection, path: Path, report: ImportReport, time_zone: str) -> None:
    data = path.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    session = conn.execute("SELECT id, file_sha256, complete FROM sessions WHERE file_name = ?", (path.name,)).fetchone()
    if session and session["complete"] and session["file_sha256"] == sha256:
        report.files_skipped += 1
        return

    result = parse_text(data.decode("utf-8-sig"), source=str(path))
    report.unrecognized.extend((path.name, u) for u in result.all_unrecognized())
    failures = [HandFailure(path.name, f.line_no, None, f.error) for f in result.failures]
    if not result.hands:
        failures.append(HandFailure(path.name, 1, None, "no hands could be parsed, so no session was created"))
        report.failures.extend(failures)
        return

    # Files list hands newest first; number them so the oldest is 1. Failed hands keep their number too.
    starts = sorted([h.line_no for h in result.hands] + [f.line_no for f in result.failures])
    order = {line_no: len(starts) - i for i, line_no in enumerate(starts)}
    oldest = result.hands[-1]

    conn.execute("BEGIN")
    try:
        session_id = session["id"] if session else None
        for hand in result.hands:
            if reason := _reject_reason(hand, oldest):
                failures.append(HandFailure(path.name, hand.line_no, hand.hand_id, reason))
                continue
            if conn.execute("SELECT 1 FROM hands WHERE hand_id = ?", (hand.hand_id,)).fetchone():
                report.hands_already_present += 1
                continue
            if session_id is None:
                # Created only once a hand needs it, so a renamed copy of an imported file adds no empty session.
                session_id = conn.execute(
                    "INSERT INTO sessions (file_name, file_sha256, table_name, currency, small_blind_cents,"
                    " big_blind_cents, max_seats) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (path.name, sha256, oldest.table_name, oldest.currency, cents(oldest.small_blind),
                     cents(oldest.big_blind), oldest.max_seats),
                ).lastrowid
            conn.execute("SAVEPOINT hand")
            try:
                _insert_hand(conn, session_id, hand, order[hand.line_no], time_zone)
            except (ValueError, sqlite3.Error) as exc:
                conn.execute("ROLLBACK TO hand")
                failures.append(HandFailure(path.name, hand.line_no, hand.hand_id, f"{type(exc).__name__}: {exc}"))
            else:
                report.hands_imported += 1
            conn.execute("RELEASE hand")

        if session_id is not None:
            complete = not failures and not result.unrecognized
            conn.execute(
                "UPDATE sessions SET file_sha256 = ?, complete = ? WHERE id = ?", (sha256, int(complete), session_id)
            )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    report.failures.extend(failures)


def _reject_reason(hand: Hand, session_hand: Hand) -> str | None:
    if hand.unrecognized:
        lines = "; ".join(f"line {u.line_no}: {u.text}" for u in hand.unrecognized)
        return f"{len(hand.unrecognized)} unrecognized line(s): {lines}"
    if hand.warnings:
        return "failed consistency checks: " + "; ".join(hand.warnings)
    if (hand.table_name, hand.stakes) != (session_hand.table_name, session_hand.stakes):
        return f"table/stakes {hand.table_name} {hand.stakes} differ from the file's {session_hand.table_name} {session_hand.stakes}"
    if unknown := sorted(set(hand.fees) - set(FEE_COLUMNS)):
        return f"summary line has fees with no column yet: {', '.join(unknown)}"
    return None


def _player_id(conn: sqlite3.Connection, session_id: int, hh_id: str, is_hero: bool) -> int:
    return conn.execute(
        "INSERT INTO players (session_id, hh_id, is_hero) VALUES (?, ?, ?)"
        " ON CONFLICT (session_id, hh_id) DO UPDATE SET is_hero = MAX(is_hero, excluded.is_hero)"
        " RETURNING id",
        (session_id, hh_id, int(is_hero)),
    ).fetchone()[0]


def _insert_hand(conn: sqlite3.Connection, session_id: int, hand: Hand, session_order: int, time_zone: str) -> None:
    later_boards = [_cards(b) for b in hand.boards[1:]] + [None, None]
    conn.execute(
        "INSERT INTO hands (hand_id, session_id, session_order, played_at, time_zone, game, small_blind_cents,"
        " big_blind_cents, button_seat, board, run_count, board_run2, board_run3, total_pot_cents, rake_cents,"
        " jackpot_cents, bingo_cents, fortune_cents, tax_cents, raw_text, parser_version)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            hand.hand_id, session_id, session_order, hand.played_at.strftime("%Y/%m/%d %H:%M:%S"), time_zone,
            hand.game, cents(hand.small_blind), cents(hand.big_blind), hand.button_seat, _cards(hand.board),
            hand.run_count, later_boards[0], later_boards[1], cents(hand.total_pot), cents(hand.rake),
            *(cents(hand.fees.get(name, Decimal(0))) for name in FEE_COLUMNS),
            hand.raw_text, PARSER_VERSION,
        ),
    )

    players = {s.player: _player_id(conn, session_id, s.player, s.player == hand.hero) for s in hand.seats}
    positions = hand.positions()
    committed = hand.committed()
    results = {r.player: r for r in hand.results}
    for s in hand.seats:
        p = s.player
        invested = committed.get(p, Decimal(0)) - sum((u.amount for u in hand.uncalled_bets if u.player == p), Decimal(0))
        collected = sum((w.amount for w in hand.collected if w.player == p), Decimal(0))
        result = results.get(p)
        shown = hand.shown_cards.get(p) or (result.cards if result else None)
        cashout = hand.cashouts.get(p)
        conn.execute(
            "INSERT INTO seats (hand_id, player_id, seat_no, position, stack_cents, dealt_in, hole_cards, showed,"
            " invested_cents, collected_cents, net_cents, time_bank_cents, cashout_chosen, cashout_received_cents,"
            " cashout_risk_cents) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                hand.hand_id, players[p], s.seat, positions.get(p), cents(s.stack), int(p in hand.dealt_in),
                _cards(shown or (hand.hero_cards if p == hand.hero else None)), int(shown is not None),
                cents(invested), cents(collected), cents(collected - invested),
                cents(result.time_bank) if result and result.time_bank else 0,
                int(bool(cashout and cashout.chose)),
                cents(cashout.received) if cashout else None, cents(cashout.risk_paid) if cashout else None,
            ),
        )

    pot = Decimal(0)
    for seq, (a, chips) in enumerate(zip(hand.actions, hand.chips_added()), 1):
        conn.execute(
            "INSERT INTO actions (hand_id, seq, street, player_id, action, amount_cents, raise_to_cents, is_all_in,"
            " pot_before_cents) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (hand.hand_id, seq, a.street, players[a.player], a.action, cents(a.amount), cents(a.raise_to),
             int(a.all_in), cents(pot)),
        )
        pot += chips


def line_type(text: str) -> str:
    """Collapse an unrecognized line to its shape, so many similar lines group together."""
    text = re.sub(r"\$[\d,.]+", "$N", text)
    text = re.sub(r"\[[^\]]*\]", "[cards]", text)
    text = re.sub(r"^Seat \d+: \S+", "Seat N: <player>", text)
    return re.sub(r"^[^:\s]+: ", "<player>: ", text)


def database_summary(conn: sqlite3.Connection) -> dict:
    multi = conn.execute(
        "SELECT hh_id, COUNT(*) AS sessions FROM players WHERE NOT is_hero GROUP BY hh_id HAVING COUNT(*) > 1"
        " ORDER BY sessions DESC, hh_id"
    ).fetchall()
    dealt = conn.execute(
        "SELECT n, COUNT(*) FROM (SELECT SUM(dealt_in) AS n FROM seats GROUP BY hand_id) GROUP BY n ORDER BY n"
    ).fetchall()
    return {
        "row_counts": db.row_counts(conn),
        "ids_in_multiple_sessions": [(r["hh_id"], r["sessions"]) for r in multi],
        "hands_by_players_dealt": {n: count for n, count in dealt},
    }


def format_report(report: ImportReport, summary: dict, list_limit: int | None = None) -> str:
    out = [
        f"Files: {report.files_found} found, {report.files_read} read, {report.files_skipped} skipped (already imported)",
        f"Hands: {report.hands_imported} imported, {report.hands_already_present} already in the database, "
        f"{len(report.failures)} failed",
    ]

    def listing(title: str, items: list[str]) -> None:
        out.append(f"\n{title}: {len(items)}")
        shown = items if list_limit is None else items[:list_limit]
        out.extend(f"  {line}" for line in shown)
        if len(shown) < len(items):
            out.append(f"  ... {len(items) - len(shown)} more in the full report")

    listing("Failed hands", [f"{f.file_name} line {f.line_no} {f.hand_id or ''}: {f.reason}" for f in report.failures])
    types = Counter(line_type(u.text) for _, u in report.unrecognized)
    listing("Unrecognized line types", [f"{n:6}  {t}" for t, n in types.most_common()])
    listing("Unrecognized lines", [f"{name} line {u.line_no}: {u.text}" for name, u in report.unrecognized])

    out.append("\nRow counts: " + ", ".join(f"{t} {n}" for t, n in summary["row_counts"].items()))
    multi = summary["ids_in_multiple_sessions"]
    out.append(f"Player IDs in more than one session: {len(multi)}")
    shown = multi if list_limit is None else multi[:list_limit]
    out.extend(f"  {hh_id}: {n} sessions" for hh_id, n in shown)
    if len(shown) < len(multi):
        out.append(f"  ... {len(multi) - len(shown)} more in the full report")
    by_dealt = summary["hands_by_players_dealt"]
    short = sum(n for players, n in by_dealt.items() if players < 6)
    out.append(f"Hands with fewer than 6 players dealt in: {short} "
               f"({', '.join(f'{p}-handed {n}' for p, n in by_dealt.items())})")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Import every GGPoker .txt hand history in a folder into SQLite.")
    ap.add_argument("folder", nargs="?", default=settings.RAW_DIR, type=Path)
    ap.add_argument("--db", default=settings.DB_PATH, type=Path, help="database file (default: data/poker.db)")
    ap.add_argument("--report", default=settings.IMPORT_REPORT_PATH, type=Path, help="where to write the full report")
    args = ap.parse_args(argv)

    conn = db.connect(args.db)
    try:
        report = import_folder(conn, args.folder)
        summary = database_summary(conn)
    finally:
        conn.close()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(format_report(report, summary) + "\n", encoding="utf-8")
    print(format_report(report, summary, list_limit=20))
    print(f"\nFull report: {args.report}")
    return 0 if not (report.failures or report.unrecognized) else 2


if __name__ == "__main__":
    sys.exit(main())
