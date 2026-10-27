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

# Bump whenever parsing changes in a way that changes what gets stored.
PARSER_VERSION = 2

STREETS = ("preflop", "flop", "turn", "river")
RUN_NUMBERS = {"FIRST": 1, "SECOND": 2, "THIRD": 3}
RUN_COUNTS = {"two": 2, "three": 3}


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
# In run-it-twice hands every street is prefixed (FIRST FLOP, ..., SECOND RIVER, FIRST SHOWDOWN).
STREET_RE = re.compile(
    r"^\*\*\* (?:(?P<run>FIRST|SECOND|THIRD) )?(?P<name>HOLE CARDS|FLOP|TURN|RIVER|SHOWDOWN|SUMMARY) \*\*\*"
    r"(?P<cards>(?: \[[^\]]+\])*)$"
)
UNCALLED_RE = re.compile(rf"^Uncalled bet \({_money('amount')}\) returned to (?P<player>.+)$")
COLLECTED_RE = re.compile(rf"^(?P<player>.+) collected {_money('amount')} from pot$")
PLAYER_LINE_RE = re.compile(r"^(?P<player>.+?): (?P<rest>.+)$")
SHOWS_RE = re.compile(r"^shows \[(?P<cards>[^\]]+)\](?: \((?P<description>.+)\))?$")
CASHOUT_CHOSEN_RE = re.compile(r"^Chooses to EV Cashout$")
CASHOUT_RECEIVED_RE = re.compile(rf"^Receives Cashout \({_money('amount')}\)$")
CASHOUT_RISK_RE = re.compile(rf"^Pays Cashout Risk \({_money('amount')}\)$")

_ALL_IN = r"(?P<all_in> and is all-in)?"
ACTION_PATTERNS = [
    ("post_sb", re.compile(rf"^posts small blind {_money('amount')}$")),
    ("post_bb", re.compile(rf"^posts big blind {_money('amount')}$")),
    # A returning player's missed small blind: dead money that doesn't count toward their bet.
    ("post_dead", re.compile(rf"^posts missed blind {_money('amount')}$")),
    # The amount is the straddler's total bet, so a BB straddling to $0.2 adds $0.1.
    ("straddle", re.compile(rf"^straddle {_money('raise_to')}$")),
    ("fold", re.compile(r"^folds$")),
    ("check", re.compile(r"^checks$")),
    ("call", re.compile(rf"^calls {_money('amount')}{_ALL_IN}$")),
    ("bet", re.compile(rf"^bets {_money('amount')}{_ALL_IN}$")),
    ("raise", re.compile(rf"^raises {_money('amount')} to {_money('raise_to')}{_ALL_IN}$")),
]

TOTAL_POT_RE = re.compile(rf"^Total pot {_money('amount')}$")
FEE_RE = re.compile(rf"^(?P<name>\w+) {_money('amount')}$")
RUN_COUNT_RE = re.compile(r"^Hand was run (?P<count>\w+) times$")
BOARD_RE = re.compile(r"^(?:(?P<run>FIRST|SECOND|THIRD) )?Board \[(?P<cards>[^\]]+)\]$")
SUMMARY_SEAT_RE = re.compile(r"^Seat (?P<seat>\d+): (?P<rest>.+)$")
POSITION_RE = re.compile(r"^ \((?P<position>button|small blind|big blind)\)")
TIME_BANK_RE = re.compile(
    rf"^(?:received \({_money('received')}\) from time bank card|bought time bank card \({_money('bought')}\)), "
)
CASHOUT_SUFFIX_RE = re.compile(rf", (?P<kind>EV Cashout|Cashout Risk) \({_money('amount')}\)$")
_WITH = r"(?: with (?P<description>.+))?"
RESULT_PATTERNS = [
    ("folded", re.compile(rf"^folded before Flop(?P<didnt_bet> \(didn't bet\))?{_WITH}$")),
    ("folded", re.compile(rf"^folded on the (?P<street>Flop|Turn|River){_WITH}$")),
    ("showed_collected", re.compile(rf"^showed \[(?P<cards>[^\]]+)\] and collected \({_money('amount')}\)$")),
    ("showed", re.compile(r"^showed \[(?P<cards>[^\]]+)\] and (?P<runs>(?:won|lost).*)$")),
    ("won", re.compile(rf"^won \({_money('amount')}\)$")),
    ("collected", re.compile(rf"^collected \({_money('amount')}\)$")),
]
RUN_SPLIT_RE = re.compile(r", and (?=won \(|lost\b)")
RUN_WON_RE = re.compile(rf"^won \({_money('amount')}\){_WITH}$")
RUN_LOST_RE = re.compile(rf"^lost{_WITH}$")


@dataclass
class Seat:
    seat: int
    player: str
    stack: Decimal


@dataclass
class Action:
    street: str  # one of STREETS
    player: str
    action: str  # post_sb, post_bb, post_dead, straddle, fold, check, call, bet, raise
    amount: Decimal | None = None  # the amount as written; for raises, the raise increment
    raise_to: Decimal | None = None  # raises and straddles: the player's total bet on this street
    all_in: bool = False


@dataclass
class PotWin:
    player: str
    amount: Decimal
    run: int = 1  # which board, in run-it-twice/three-times hands


@dataclass
class UncalledBet:
    player: str
    amount: Decimal


@dataclass
class Cashout:
    """GGPoker's all-in insurance ("EV Cashout"). Paid outside the pot."""

    chose: bool = False
    received: Decimal | None = None  # paid to a player who cashed out and then lost
    risk_paid: Decimal | None = None  # given up by a player who cashed out and then won


@dataclass
class RunResult:
    won: bool
    amount: Decimal | None = None
    description: str | None = None


@dataclass
class SeatResult:
    """One ``Seat N: ...`` line from the summary."""

    seat: int
    player: str
    positions: list[str]  # "button", "small blind", "big blind"
    outcome: str  # folded, showed_won, showed_lost, showed_collected, won, collected
    fold_street: str | None = None
    didnt_bet: bool = False
    amount: Decimal | None = None  # total won, across all runs
    cards: list[str] | None = None
    description: str | None = None  # first run's hand; for folds, the hand the board alone made
    runs: list[RunResult] = field(default_factory=list)  # showed_won/showed_lost: one per board
    time_bank: Decimal | None = None  # received from (+) or paid for (-) a time bank card
    cashout_received: Decimal | None = None
    cashout_risk: Decimal | None = None


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
    dealt_in: list[str] = field(default_factory=list)
    hero: str | None = None
    hero_cards: list[str] | None = None
    actions: list[Action] = field(default_factory=list)
    boards: list[list[str]] = field(default_factory=lambda: [[]])  # one full board per run
    run_count: int = 1
    shown_cards: dict[str, list[str]] = field(default_factory=dict)
    cashouts: dict[str, Cashout] = field(default_factory=dict)
    collected: list[PotWin] = field(default_factory=list)  # one entry per pot and run, so players repeat
    uncalled_bets: list[UncalledBet] = field(default_factory=list)
    total_pot: Decimal | None = None
    rake: Decimal | None = None
    fees: dict[str, Decimal] = field(default_factory=dict)  # Jackpot, Bingo, Fortune, Tax, ...
    summary_boards: dict[int, list[str]] = field(default_factory=dict)  # run -> cards as listed
    results: list[SeatResult] = field(default_factory=list)
    unrecognized: list[UnrecognizedLine] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw_text: str = ""
    line_no: int = 0  # line of the "Poker Hand #" header in the file

    @property
    def stakes(self) -> str:
        return f"{self.currency}{self.small_blind}/{self.currency}{self.big_blind}"

    @property
    def board(self) -> list[str]:
        return self.boards[0]

    def chips_added(self) -> list[Decimal]:
        """Chips each action moved into the pot, aligned with ``actions``."""
        added = []
        street_bets: dict[str, Decimal] = {}
        street = None
        for a in self.actions:
            if a.street != street:
                street, street_bets = a.street, {}
            if a.action == "post_dead":
                added.append(a.amount)
                continue
            before = street_bets.get(a.player, Decimal(0))
            if a.raise_to is not None:
                after = a.raise_to
            elif a.amount is not None:
                after = before + a.amount
            else:
                after = before
            street_bets[a.player] = after
            added.append(after - before)
        return added

    def committed(self) -> dict[str, Decimal]:
        """Chips each player put into the pot, before uncalled bets are returned."""
        totals: dict[str, Decimal] = {}
        for a, chips in zip(self.actions, self.chips_added()):
            if chips:
                totals[a.player] = totals.get(a.player, Decimal(0)) + chips
        return totals

    def positions(self) -> dict[str, str]:
        """Position of each dealt-in player, counted back from the button.

        6 players: UTG HJ CO BTN SB BB; fewer players drop the earliest seats.
        Heads-up, the button posts the small blind and is labelled BTN/SB.
        """
        seats = sorted((s for s in self.seats if s.player in self.dealt_in), key=lambda s: s.seat)
        if len(seats) < 2:
            return {s.player: "BTN" for s in seats}
        # Rotate so the button is last. If the button seat is empty, the last seat before it acts as button.
        before = [s for s in seats if s.seat <= self.button_seat]
        button_index = seats.index(before[-1]) if before else len(seats) - 1
        order = seats[button_index + 1:] + seats[: button_index + 1]  # SB, BB, ..., BTN
        if len(order) == 2:
            return {order[1].player: "BTN/SB", order[0].player: "BB"}
        extra = len(order) - 3  # seats besides the blinds and button
        if extra <= 3:
            early = ["UTG", "HJ", "CO"][3 - extra:]
        else:  # bigger than 6-max: UTG, UTG+1, ..., HJ, CO
            early = ["UTG"] + [f"UTG+{i}" for i in range(1, extra - 2)] + ["HJ", "CO"]
        labels = ["SB", "BB"] + early + ["BTN"]
        return {s.player: label for s, label in zip(order, labels)}


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
        self.showdown_run = 1

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
            self.hand.dealt_in.append(m["player"])
            if m["cards"]:
                self.hand.hero = m["player"]
                self.hand.hero_cards = m["cards"].split()
            return True
        if m := UNCALLED_RE.match(line):
            self.hand.uncalled_bets.append(UncalledBet(m["player"], _dec(m["amount"])))
            return True
        if m := COLLECTED_RE.match(line):
            self.hand.collected.append(PotWin(m["player"], _dec(m["amount"]), self.showdown_run))
            return True
        if m := PLAYER_LINE_RE.match(line):
            return self._player_line(m["player"], m["rest"])
        return False

    def _street_line(self, m: re.Match) -> bool:
        name, run = m["name"], RUN_NUMBERS.get(m["run"], 1)
        groups = re.findall(r"\[([^\]]+)\]", m["cards"])
        if name in ("HOLE CARDS", "SUMMARY"):
            if groups or m["run"]:
                return False
            self.section = "play" if name == "HOLE CARDS" else "summary"
            return True
        if name == "SHOWDOWN":
            if groups:
                return False
            self.section, self.showdown_run = "showdown", run
            return True
        if not groups:
            return False
        previous = [c for g in groups[:-1] for c in g.split()]
        if run == 1:
            board = self.hand.boards[0]
        else:
            while len(self.hand.boards) < run:
                self.hand.boards.append([])
            board = self.hand.boards[run - 1]
            if not board:
                # A later run starts from the cards all runs share, which must match run 1.
                if previous != self.hand.boards[0][: len(previous)]:
                    self.hand.warnings.append(f"run {run} starts from {previous}, not run 1's board")
                board.extend(previous)
        if previous != board:
            self.hand.warnings.append(f"{m[0]} repeats board {previous}, expected {board}")
        board.extend(groups[-1].split())
        self.street = name.lower()
        return True

    def _player_line(self, player: str, rest: str) -> bool:
        if m := SHOWS_RE.match(rest):
            self.hand.shown_cards[player] = m["cards"].split()
            return True
        if CASHOUT_CHOSEN_RE.match(rest):
            self.hand.cashouts.setdefault(player, Cashout()).chose = True
            return True
        if m := CASHOUT_RECEIVED_RE.match(rest):
            self.hand.cashouts.setdefault(player, Cashout()).received = _dec(m["amount"])
            return True
        if m := CASHOUT_RISK_RE.match(rest):
            self.hand.cashouts.setdefault(player, Cashout()).risk_paid = _dec(m["amount"])
            return True
        for action, pattern in ACTION_PATTERNS:
            if m := pattern.match(rest):
                groups = m.groupdict()
                raise_to = _dec(groups["raise_to"]) if groups.get("raise_to") else None
                self.hand.actions.append(
                    Action(
                        street=self.street,
                        player=player,
                        action=action,
                        amount=_dec(groups["amount"]) if groups.get("amount") else raise_to,
                        raise_to=raise_to,
                        all_in=bool(groups.get("all_in")),
                    )
                )
                return True
        return False

    def _summary_line(self, line: str) -> bool:
        if line.startswith("Total pot "):
            return self._pot_line(line)
        if m := RUN_COUNT_RE.match(line):
            if m["count"] not in RUN_COUNTS:
                return False
            self.hand.run_count = RUN_COUNTS[m["count"]]
            return True
        if m := BOARD_RE.match(line):
            self.hand.summary_boards[RUN_NUMBERS.get(m["run"], 1)] = m["cards"].split()
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
        result = SeatResult(seat=seat, player=player, positions=positions, outcome="")
        rest = rest[1:]
        if m := TIME_BANK_RE.match(rest):
            result.time_bank = _dec(m["received"]) if m["received"] else -_dec(m["bought"])
            rest = rest[m.end():]
        if m := CASHOUT_SUFFIX_RE.search(rest):
            if m["kind"] == "EV Cashout":
                result.cashout_received = _dec(m["amount"])
            else:
                result.cashout_risk = _dec(m["amount"])
            rest = rest[: m.start()]

        for outcome, pattern in RESULT_PATTERNS:
            if not (m := pattern.match(rest)):
                continue
            g = m.groupdict()
            result.outcome = outcome
            result.didnt_bet = bool(g.get("didnt_bet"))
            result.amount = _dec(g["amount"]) if g.get("amount") else None
            result.cards = g["cards"].split() if g.get("cards") else None
            result.description = g.get("description")
            if outcome == "folded":
                result.fold_street = g["street"].lower() if g.get("street") else "preflop"
            if outcome == "showed":
                if not self._run_results(result, g["runs"]):
                    return False
            self.hand.results.append(result)
            return True
        return False

    @staticmethod
    def _run_results(result: SeatResult, text: str) -> bool:
        for part in RUN_SPLIT_RE.split(text):
            if m := RUN_WON_RE.match(part):
                result.runs.append(RunResult(True, _dec(m["amount"]), m["description"]))
            elif m := RUN_LOST_RE.match(part):
                result.runs.append(RunResult(False, None, m["description"]))
            else:
                return False
        won = [r.amount for r in result.runs if r.won]
        result.outcome = "showed_won" if won else "showed_lost"
        result.amount = sum(won, Decimal(0)) if won else None
        result.description = result.runs[0].description
        return True


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
        line_no=lines[0][0],
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
        hand.dealt_in
        + [a.player for a in hand.actions]
        + [w.player for w in hand.collected]
        + [u.player for u in hand.uncalled_bets]
        + list(hand.shown_cards)
        + list(hand.cashouts)
    )
    for player in sorted(set(named) - seated):
        problems.append(f"{player!r} acts but has no seat")

    if len(hand.boards) != hand.run_count:
        problems.append(f"hand was run {hand.run_count} times but has {len(hand.boards)} boards")
    for run, board in enumerate(hand.boards, 1):
        if len(board) not in ((0, 3, 4, 5) if run == 1 else (5,)):
            problems.append(f"board {run} has {len(board)} cards")
        listed = hand.summary_boards.get(run)
        if listed is None:
            if board:
                problems.append(f"board {run} missing from summary")
        elif board[len(board) - len(listed):] != listed:
            # Later runs list only the cards that differ from the shared part.
            problems.append(f"summary board {run} {listed} doesn't match dealt board {board}")
    if hand.total_pot is None:
        problems.append("no 'Total pot' summary line")
        return problems

    put_in = sum(hand.committed().values(), Decimal(0)) - sum((u.amount for u in hand.uncalled_bets), Decimal(0))
    if put_in != hand.total_pot:
        problems.append(f"bets minus uncalled = {put_in}, but total pot is {hand.total_pot}")
    paid_out = sum((w.amount for w in hand.collected), Decimal(0)) + hand.rake + sum(hand.fees.values(), Decimal(0))
    if paid_out != hand.total_pot:
        problems.append(f"collected + rake + fees = {paid_out}, but total pot is {hand.total_pot}")

    if {r.player for r in hand.results} != seated:
        problems.append("summary doesn't list every seated player")
    for r in hand.results:
        won = sum((w.amount for w in hand.collected if w.player == r.player), Decimal(0))
        cashout = hand.cashouts.get(r.player, Cashout())
        if r.cashout_received is not None:
            # After an EV Cashout the summary shows "won ($0)" and folds the player's pot share into the
            # cashout figure, e.g. "EV Cashout ($14.04)" = collected $7.26 + Receives Cashout $6.78.
            if r.cashout_received != won + (cashout.received or 0) or r.amount:
                problems.append(f"{r.player} EV Cashout {r.cashout_received} != collected {won} + {cashout.received}")
        elif cashout.received is not None:
            problems.append(f"{r.player} received a cashout the summary doesn't show")
        elif won != (r.amount or 0):
            problems.append(f"{r.player} collected {won} but summary says {r.amount or 0}")
        if r.cashout_risk != cashout.risk_paid:
            problems.append(f"{r.player} paid cashout risk {cashout.risk_paid} but summary says {r.cashout_risk}")
        if r.cards and hand.shown_cards.get(r.player, r.cards) != r.cards:
            problems.append(f"{r.player} showed {hand.shown_cards[r.player]} but summary says {r.cards}")
    return problems


def parse_text(text: str, source: str = "<text>") -> ParseResult:
    result = ParseResult(source=source)
    all_lines = text.lstrip("﻿").splitlines()
    chunk: list[tuple[int, str]] = []

    def flush() -> None:
        if not chunk:
            return
        try:
            hand = parse_hand(chunk)
        except Exception as exc:  # one broken hand must not stop the file; it is reported instead
            result.failures.append(ParseFailure(chunk[0][0], chunk[0][1], f"{type(exc).__name__}: {exc}"))
            return
        hand.raw_text = "\n".join(all_lines[chunk[0][0] - 1 : chunk[-1][0]])
        result.hands.append(hand)

    for line_no, raw in enumerate(all_lines, 1):
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
