"""Parse GGPoker No Limit Hold'em hand history text files into dataclasses.

Every line of a hand is either understood or recorded in ``Hand.unrecognized``;
nothing is dropped silently. Hands that cannot be parsed at all are reported as
failures, and every parsed hand is run through consistency checks (chip totals,
board, seat names) whose problems land in ``Hand.warnings``.

Run ``python -m poker_analyzer.parser [files or folders]`` for a report.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

STREETS = ("preflop", "flop", "turn", "river")


def _money(name: str) -> str:
    return rf"\$?(?P<{name}>[\d,]+(?:\.\d+)?)"


def _dec(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


HEADER_RE = re.compile(
    r"^Poker Hand #(?P<hand_id>\S+): (?P<game>.+?) "
    r"\((?P<currency>[^\d\s/]*)(?P<sb>[\d,.]+)/[^\d\s/]*(?P<bb>[\d,.]+)\) - "
    r"(?P<played_at>\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})$"
)
TABLE_RE = re.compile(r"^Table '(?P<table>.+)' (?P<max_seats>\d+)-max Seat #(?P<button>\d+) is the button$")
SEAT_RE = re.compile(rf"^Seat (?P<seat>\d+): (?P<player>.+) \({_money('stack')} in chips\)$")
DEALT_RE = re.compile(r"^Dealt to (?P<player>.+?)(?: \[(?P<cards>[^\]]+)\])?$")
STREET_RE = re.compile(
    r"^\*\*\* (?P<name>HOLE CARDS|FLOP|TURN|RIVER|SHOWDOWN|SUMMARY) \*\*\*(?P<cards>(?: \[[^\]]+\])*)$"
)
UNCALLED_RE = re.compile(rf"^Uncalled bet \({_money('amount')}\) returned to (?P<player>.+)$")
COLLECTED_RE = re.compile(rf"^(?P<player>.+) collected {_money('amount')} from pot$")
PLAYER_LINE_RE = re.compile(r"^(?P<player>.+?): (?P<rest>.+)$")
SHOWS_RE = re.compile(r"^shows \[(?P<cards>[^\]]+)\](?: \((?P<description>.+)\))?$")

_ALL_IN = r"(?P<all_in> and is all-in)?"
ACTION_PATTERNS = [
    ("post_sb", re.compile(rf"^posts small blind {_money('amount')}$")),
    ("post_bb", re.compile(rf"^posts big blind {_money('amount')}$")),
    ("fold", re.compile(r"^folds$")),
    ("check", re.compile(r"^checks$")),
    ("call", re.compile(rf"^calls {_money('amount')}{_ALL_IN}$")),
    ("bet", re.compile(rf"^bets {_money('amount')}{_ALL_IN}$")),
    ("raise", re.compile(rf"^raises {_money('amount')} to {_money('raise_to')}{_ALL_IN}$")),
]

TOTAL_POT_RE = re.compile(rf"^Total pot {_money('amount')}$")
FEE_RE = re.compile(rf"^(?P<name>\w+) {_money('amount')}$")
BOARD_RE = re.compile(r"^Board \[(?P<cards>[^\]]+)\]$")
SUMMARY_SEAT_RE = re.compile(r"^Seat (?P<seat>\d+): (?P<rest>.+)$")
POSITION_RE = re.compile(r"^ \((?P<position>button|small blind|big blind)\)")
RESULT_PATTERNS = [
    ("folded", re.compile(r"^folded before Flop(?P<didnt_bet> \(didn't bet\))?$")),
    ("folded", re.compile(r"^folded on the (?P<street>Flop|Turn|River)$")),
    (
        "showed_won",
        re.compile(rf"^showed \[(?P<cards>[^\]]+)\] and won \({_money('amount')}\)(?: with (?P<description>.+))?$"),
    ),
    ("showed_lost", re.compile(r"^showed \[(?P<cards>[^\]]+)\] and lost(?: with (?P<description>.+))?$")),
    ("won", re.compile(rf"^won \({_money('amount')}\)$")),
    ("collected", re.compile(rf"^collected \({_money('amount')}\)$")),
]


@dataclass
class Seat:
    seat: int
    player: str
    stack: Decimal


@dataclass
class Action:
    street: str  # one of STREETS
    player: str
    action: str  # post_sb, post_bb, fold, check, call, bet, raise
    amount: Decimal | None = None  # the amount as written; for raises, the raise increment
    raise_to: Decimal | None = None  # raises only: the player's total bet on this street
    all_in: bool = False


@dataclass
class PotWin:
    player: str
    amount: Decimal


@dataclass
class UncalledBet:
    player: str
    amount: Decimal


@dataclass
class SeatResult:
    """One ``Seat N: ...`` line from the summary."""

    seat: int
    player: str
    positions: list[str]  # "button", "small blind", "big blind"
    outcome: str  # folded, showed_won, showed_lost, won, collected
    fold_street: str | None = None
    didnt_bet: bool = False
    amount: Decimal | None = None
    cards: list[str] | None = None
    description: str | None = None


@dataclass
class UnrecognizedLine:
    line_no: int
    text: str


@dataclass
class Hand:
    hand_id: str
    game: str
    currency: str
    small_blind: Decimal
    big_blind: Decimal
    played_at: datetime
    table_name: str
    max_seats: int
    button_seat: int
    seats: list[Seat] = field(default_factory=list)
    hero: str | None = None
    hero_cards: list[str] | None = None
    actions: list[Action] = field(default_factory=list)
    board: list[str] = field(default_factory=list)
    shown_cards: dict[str, list[str]] = field(default_factory=dict)
    collected: list[PotWin] = field(default_factory=list)  # one entry per pot won, so side pots repeat players
    uncalled_bets: list[UncalledBet] = field(default_factory=list)
    total_pot: Decimal | None = None
    rake: Decimal | None = None
    fees: dict[str, Decimal] = field(default_factory=dict)  # Jackpot, Bingo, Fortune, Tax, ...
    summary_board: list[str] | None = None
    results: list[SeatResult] = field(default_factory=list)
    unrecognized: list[UnrecognizedLine] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def stakes(self) -> str:
        return f"{self.currency}{self.small_blind}/{self.currency}{self.big_blind}"

    def committed(self) -> dict[str, Decimal]:
        """Chips each player put into the pot, before uncalled bets are returned."""
        totals: dict[str, Decimal] = {}
        street_bets: dict[str, Decimal] = {}
        street = None
        for a in self.actions:
            if a.street != street:
                street, street_bets = a.street, {}
            before = street_bets.get(a.player, Decimal(0))
            if a.action == "raise":
                after = a.raise_to
            elif a.amount is not None:
                after = before + a.amount
            else:
                continue
            street_bets[a.player] = after
            totals[a.player] = totals.get(a.player, Decimal(0)) + after - before
        return totals


@dataclass
class ParseFailure:
    line_no: int
    header: str
    error: str


@dataclass
class ParseResult:
    source: str
    hands: list[Hand] = field(default_factory=list)
    failures: list[ParseFailure] = field(default_factory=list)
    unrecognized: list[UnrecognizedLine] = field(default_factory=list)  # lines outside any hand

    def all_unrecognized(self) -> list[UnrecognizedLine]:
        lines = list(self.unrecognized)
        for hand in self.hands:
            lines.extend(hand.unrecognized)
        return sorted(lines, key=lambda u: u.line_no)


class HandParseError(ValueError):
    pass


class _HandBuilder:
    def __init__(self, hand: Hand):
        self.hand = hand
        self.street = "preflop"
        self.section = "setup"  # setup -> play -> showdown -> summary

    def feed(self, line: str) -> bool:
        """Apply one line to the hand. Returns False if the line wasn't understood."""
        if self.section == "summary":
            return self._summary_line(line)
        if m := STREET_RE.match(line):
            return self._street_line(m)
        if self.section == "setup" and (m := SEAT_RE.match(line)):
            self.hand.seats.append(Seat(int(m["seat"]), m["player"], _dec(m["stack"])))
            return True
        if m := DEALT_RE.match(line):
            if m["cards"]:
                self.hand.hero = m["player"]
                self.hand.hero_cards = m["cards"].split()
            return True
        if m := UNCALLED_RE.match(line):
            self.hand.uncalled_bets.append(UncalledBet(m["player"], _dec(m["amount"])))
            return True
        if m := COLLECTED_RE.match(line):
            self.hand.collected.append(PotWin(m["player"], _dec(m["amount"])))
            return True
        if m := PLAYER_LINE_RE.match(line):
            return self._player_line(m["player"], m["rest"])
        return False

    def _street_line(self, m: re.Match) -> bool:
        name, groups = m["name"], re.findall(r"\[([^\]]+)\]", m["cards"])
        if name in ("HOLE CARDS", "SHOWDOWN", "SUMMARY"):
            if groups:
                return False
            self.section = {"HOLE CARDS": "play", "SHOWDOWN": "showdown", "SUMMARY": "summary"}[name]
            return True
        if not groups:
            return False
        previous = [c for g in groups[:-1] for c in g.split()]
        if previous != self.hand.board:
            self.hand.warnings.append(f"{name} line repeats board {previous}, expected {self.hand.board}")
        self.hand.board.extend(groups[-1].split())
        self.street = name.lower()
        return True

    def _player_line(self, player: str, rest: str) -> bool:
        if m := SHOWS_RE.match(rest):
            self.hand.shown_cards[player] = m["cards"].split()
            return True
        for action, pattern in ACTION_PATTERNS:
            if m := pattern.match(rest):
                groups = m.groupdict()
                self.hand.actions.append(
                    Action(
                        street=self.street,
                        player=player,
                        action=action,
                        amount=_dec(groups["amount"]) if groups.get("amount") else None,
                        raise_to=_dec(groups["raise_to"]) if groups.get("raise_to") else None,
                        all_in=bool(groups.get("all_in")),
                    )
                )
                return True
        return False

    def _summary_line(self, line: str) -> bool:
        if line.startswith("Total pot "):
            return self._pot_line(line)
        if m := BOARD_RE.match(line):
            self.hand.summary_board = m["cards"].split()
            return True
        if m := SUMMARY_SEAT_RE.match(line):
            return self._seat_result(int(m["seat"]), m["rest"])
        return False

    def _pot_line(self, line: str) -> bool:
        parts = line.split(" | ")
        if not (m := TOTAL_POT_RE.match(parts[0])):
            return False
        fees = {}
        for part in parts[1:]:
            if not (f := FEE_RE.match(part)):
                return False
            fees[f["name"]] = _dec(f["amount"])
        if "Rake" not in fees:
            return False
        self.hand.total_pot = _dec(m["amount"])
        self.hand.rake = fees.pop("Rake")
        self.hand.fees = fees
        return True

    def _seat_result(self, seat: int, rest: str) -> bool:
        # Use the name from the seat list so names containing spaces or brackets can't confuse the regexes.
        player = next((s.player for s in self.hand.seats if s.seat == seat), None)
        if player is None or not rest.startswith(player + " "):
            return False
        rest = rest[len(player):]
        positions = []
        while m := POSITION_RE.match(rest):
            positions.append(m["position"])
            rest = rest[m.end():]
        rest = rest[1:]
        for outcome, pattern in RESULT_PATTERNS:
            if m := pattern.match(rest):
                g = m.groupdict()
                self.hand.results.append(
                    SeatResult(
                        seat=seat,
                        player=player,
                        positions=positions,
                        outcome=outcome,
                        fold_street=g["street"].lower() if g.get("street") else "preflop" if outcome == "folded" else None,
                        didnt_bet=bool(g.get("didnt_bet")),
                        amount=_dec(g["amount"]) if g.get("amount") else None,
                        cards=g["cards"].split() if g.get("cards") else None,
                        description=g.get("description"),
                    )
                )
                return True
        return False


def parse_hand(lines: list[tuple[int, str]]) -> Hand:
    """Parse one hand from (line number, text) pairs, the first being the ``Poker Hand #`` line."""
    if len(lines) < 2:
        raise HandParseError("hand has fewer than two lines")
    (_, header_line), (_, table_line) = lines[0], lines[1]
    if not (header := HEADER_RE.match(header_line)):
        raise HandParseError(f"unrecognized header: {header_line!r}")
    if not (table := TABLE_RE.match(table_line)):
        raise HandParseError(f"unrecognized table line: {table_line!r}")
    hand = Hand(
        hand_id=header["hand_id"],
        game=header["game"],
        currency=header["currency"],
        small_blind=_dec(header["sb"]),
        big_blind=_dec(header["bb"]),
        played_at=datetime.strptime(header["played_at"], "%Y/%m/%d %H:%M:%S"),
        table_name=table["table"],
        max_seats=int(table["max_seats"]),
        button_seat=int(table["button"]),
    )
    builder = _HandBuilder(hand)
    for line_no, line in lines[2:]:
        if not builder.feed(line):
            hand.unrecognized.append(UnrecognizedLine(line_no, line))
    hand.warnings.extend(validate(hand))
    return hand


def validate(hand: Hand) -> list[str]:
    """Consistency checks that catch lines the parser misread."""
    problems = []
    seated = {s.player for s in hand.seats}
    if not hand.seats:
        problems.append("no seats")
    named = (
        [a.player for a in hand.actions]
        + [w.player for w in hand.collected]
        + [u.player for u in hand.uncalled_bets]
        + list(hand.shown_cards)
    )
    for player in sorted(set(named) - seated):
        problems.append(f"{player!r} acts but has no seat")
    if len(hand.board) not in (0, 3, 4, 5):
        problems.append(f"board has {len(hand.board)} cards")
    if hand.summary_board is not None and hand.summary_board != hand.board:
        problems.append(f"summary board {hand.summary_board} != dealt board {hand.board}")
    if hand.total_pot is None:
        problems.append("no 'Total pot' summary line")
        return problems

    put_in = sum(hand.committed().values(), Decimal(0)) - sum((u.amount for u in hand.uncalled_bets), Decimal(0))
    if put_in != hand.total_pot:
        problems.append(f"bets minus uncalled = {put_in}, but total pot is {hand.total_pot}")
    paid_out = sum((w.amount for w in hand.collected), Decimal(0)) + hand.rake + sum(hand.fees.values(), Decimal(0))
    if paid_out != hand.total_pot:
        problems.append(f"collected + rake + fees = {paid_out}, but total pot is {hand.total_pot}")

    for player in seated:
        won = sum((w.amount for w in hand.collected if w.player == player), Decimal(0))
        summary_won = sum((r.amount for r in hand.results if r.player == player and r.amount), Decimal(0))
        if won != summary_won:
            problems.append(f"{player} collected {won} but summary says {summary_won}")
    return problems


def parse_text(text: str, source: str = "<text>") -> ParseResult:
    result = ParseResult(source=source)
    chunk: list[tuple[int, str]] = []

    def flush() -> None:
        if not chunk:
            return
        try:
            result.hands.append(parse_hand(chunk))
        except Exception as exc:  # one broken hand must not stop the file; it is reported instead
            result.failures.append(ParseFailure(chunk[0][0], chunk[0][1], f"{type(exc).__name__}: {exc}"))

    for line_no, raw in enumerate(text.lstrip("﻿").splitlines(), 1):
        line = raw.rstrip()
        if line.startswith("Poker Hand #"):
            flush()
            chunk = [(line_no, line)]
        elif not line:
            continue
        elif chunk:
            chunk.append((line_no, line))
        else:
            result.unrecognized.append(UnrecognizedLine(line_no, line))
    flush()
    return result


def parse_file(path: str | Path) -> ParseResult:
    path = Path(path)
    return parse_text(path.read_text(encoding="utf-8-sig"), source=str(path))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Parse GGPoker hand histories and report problems.")
    ap.add_argument("paths", nargs="*", default=["data/raw"], help="hand history files or folders")
    args = ap.parse_args(argv)

    files = []
    for p in map(Path, args.paths):
        files.extend(sorted(p.glob("*.txt")) if p.is_dir() else [p])
    if not files:
        print("No hand history files found.")
        return 1

    total_hands = total_failed = total_unrecognized = total_warned = 0
    for f in files:
        result = parse_file(f)
        unrecognized = result.all_unrecognized()
        warned = [h for h in result.hands if h.warnings]
        total_hands += len(result.hands)
        total_failed += len(result.failures)
        total_unrecognized += len(unrecognized)
        total_warned += len(warned)

        print(f"{f.name}: {len(result.hands)} parsed, {len(result.failures)} failed, "
              f"{len(unrecognized)} unrecognized lines, {len(warned)} hands with warnings")
        for fail in result.failures:
            print(f"  FAILED line {fail.line_no}: {fail.error}")
        for u in unrecognized:
            print(f"  UNRECOGNIZED line {u.line_no}: {u.text}")
        for hand in warned:
            for w in hand.warnings:
                print(f"  WARNING {hand.hand_id}: {w}")

    if len(files) > 1:
        print(f"Total: {total_hands} parsed, {total_failed} failed, "
              f"{total_unrecognized} unrecognized lines, {total_warned} hands with warnings")
    return 0 if not (total_failed or total_unrecognized or total_warned) else 2


if __name__ == "__main__":
    sys.exit(main())
