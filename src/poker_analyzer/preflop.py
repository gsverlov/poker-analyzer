"""Hero's preflop decisions: the situation, Hero's cards and action, and the result from that point on.

Results count only money Hero puts in from the decision onward, so blinds and
earlier bets are sunk and a fold is worth 0. When Hero is all-in with cards
shown before the river, Hero's share of the pot is Hero's exact equity times
the pot after rake and fees, instead of what actually happened (this also
replaces run-it-twice and EV Cashout outcomes).
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .equity import cards as parse_cards
from .equity import equity

RANKS = "AKQJT98765432"  # grid order, strongest first

SITUATIONS = {
    "rfi": "RFI: folded to Hero",
    "bvb": "Blind vs blind: folded to Hero in the SB",
    "vs_open": "Facing an open",
    "squeeze": "Squeeze spot: an open plus callers",
    "vs_limpers": "Facing limpers",
    "vs_3bet": "Facing a 3-bet after Hero opened",
    "vs_4bet": "Facing a 4-bet after Hero 3-bet",
    "bb_vs_sb_limp": "BB facing an SB limp",
    "sb_limp_vs_bb_raise": "SB limped, facing a BB raise",
    "other": "Other",
}

# Open-size buckets, from the distribution of opens in the data: 29% exact min-raises,
# 31% between 2.1 and 2.9bb (mostly 2.2 and 2.5), 32% exactly 3bb, and 8% bigger.
SIZE_BUCKETS = [("min-raise (2bb)", 2.0), ("small (2.1-2.9bb)", 2.95), ("3bb", 3.05), ("large (over 3bb)", float("inf"))]

# Postflop acting order, used to tell whether Hero is in position.
POSTFLOP_ORDER = {"SB": 0, "BB": 1, "UTG": 2, "UTG+1": 3, "UTG+2": 4, "HJ": 5, "CO": 6, "BTN": 7, "BTN/SB": 8}

STREET_CARDS = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}


@dataclass
class Decision:
    hand_id: str
    situation: str
    hero_position: str
    villain_position: str | None  # opener, 3-bettor, 4-bettor or limping SB, depending on the situation
    hole_cards: str
    hand: str  # e.g. AKs, 72o, TT
    group: str
    action: str  # fold, check, call, raise
    hero_all_in: bool
    raise_to_bb: float | None  # Hero's raise size
    faced_bb: float | None  # size of the raise Hero faced
    limpers: int
    callers: int
    result_bb: float
    all_in_ev: bool  # result uses all-in equity
    other_kind: str | None = None  # what the "other" situation was

    @property
    def size_bucket(self) -> str | None:
        if self.faced_bb is None or self.situation not in ("vs_open", "squeeze"):
            return None
        return next(name for name, upper in SIZE_BUCKETS if self.faced_bb <= upper)

    @property
    def basic_action(self) -> str:
        """fold, call or raise, with a check counted as a call."""
        return "call" if self.action == "check" else self.action

    @property
    def in_position(self) -> bool | None:
        if self.villain_position is None:
            return None
        return POSTFLOP_ORDER[self.hero_position] > POSTFLOP_ORDER[self.villain_position]


@dataclass
class DecisionSet:
    decisions: list[Decision] = field(default_factory=list)
    hands_seen: int = 0
    excluded: Counter = field(default_factory=Counter)  # reason -> hands
    all_in_hands: int = 0  # hands whose results use all-in equity
    all_in_unshown: int = 0  # all-in before the river but some cards weren't shown, so actual results were used
    opponent_open_sizes: Counter = field(default_factory=Counter)  # bb -> count, opens by anyone but Hero


def hand_class(hole_cards: str) -> str:
    (r1, s1), (r2, s2) = hole_cards.split()
    a, b = sorted((r1.upper(), r2.upper()), key=RANKS.index)
    if a == b:
        return a + b
    return a + b + ("s" if s1 == s2 else "o")


def hand_group(hand: str) -> str:
    hi, lo = RANKS.index(hand[0]), RANKS.index(hand[1])  # 0 = ace
    broadway = lo <= RANKS.index("T")
    if len(hand) == 2:
        if hi <= RANKS.index("Q"):
            return "Big pairs (QQ+)"
        return "Medium pairs (77-JJ)" if hi <= RANKS.index("7") else "Small pairs (22-66)"
    gap = lo - hi
    if hand.endswith("s"):
        if broadway:
            return "Suited broadways"
        if hand[0] == "A":
            return "Suited wheel aces (A2s-A5s)" if lo >= RANKS.index("5") else "Other suited aces (A6s-A9s)"
        if gap == 1 and RANKS.index("T") <= hi <= RANKS.index("5"):
            return "Suited connectors (54s-T9s)"
        if gap == 2 and RANKS.index("J") <= hi <= RANKS.index("5"):
            return "Suited one-gappers (53s-J9s)"
        return "Other suited"
    if broadway:
        return "Offsuit broadways"
    if hand[0] == "A":
        return "Offsuit aces (A2o-A9o)"
    return "Other offsuit"


HAND_GROUPS = [
    "Big pairs (QQ+)", "Medium pairs (77-JJ)", "Small pairs (22-66)", "Suited broadways",
    "Suited wheel aces (A2s-A5s)", "Other suited aces (A6s-A9s)", "Suited connectors (54s-T9s)",
    "Suited one-gappers (53s-J9s)", "Other suited", "Offsuit broadways", "Offsuit aces (A2o-A9o)", "Other offsuit",
]


@dataclass
class _Seat:
    position: str | None
    hole_cards: str | None
    invested: int
    collected: int
    is_hero: bool


@dataclass
class _Action:
    seq: int
    street: str
    player: int
    action: str
    amount: int | None
    raise_to: int | None
    all_in: bool


def _load(conn: sqlite3.Connection):
    seats: dict[str, dict[int, _Seat]] = defaultdict(dict)
    for r in conn.execute(
        "SELECT s.hand_id, s.player_id, s.position, s.hole_cards, s.invested_cents, s.collected_cents, p.is_hero"
        " FROM seats s JOIN players p ON p.id = s.player_id"
    ):
        seats[r[0]][r[1]] = _Seat(r[2], r[3], r[4], r[5], bool(r[6]))
    actions: dict[str, list[_Action]] = defaultdict(list)
    for r in conn.execute(
        "SELECT hand_id, seq, street, player_id, action, amount_cents, raise_to_cents, is_all_in FROM actions"
        " ORDER BY hand_id, seq"
    ):
        actions[r[0]].append(_Action(r[1], r[2], r[3], r[4], r[5], r[6], bool(r[7])))
    hands = conn.execute(
        "SELECT hand_id, big_blind_cents, total_pot_cents,"
        " rake_cents + jackpot_cents + bingo_cents + fortune_cents + tax_cents, board FROM hands ORDER BY hand_id"
    ).fetchall()
    for hand_id, bb, pot, fees, board in hands:
        yield hand_id, bb, pot, fees, (board or "").split(), seats[hand_id], actions[hand_id]


def _chips_added(actions: list[_Action]) -> list[int]:
    """Chips each action put in the pot, in cents (same rules as Hand.chips_added)."""
    added, street_bets, street = [], {}, None
    for a in actions:
        if a.street != street:
            street, street_bets = a.street, {}
        if a.action == "post_dead":
            added.append(a.amount)
            continue
        before = street_bets.get(a.player, 0)
        after = a.raise_to if a.raise_to is not None else before + (a.amount or 0)
        street_bets[a.player] = after
        added.append(after - before)
    return added


class _EquityCache:
    def __init__(self, path: Path | None):
        self.path = path
        self.data = json.loads(path.read_text()) if path and path.exists() else {}
        self.dirty = False

    def get(self, holes: list[str], board: list[str]) -> list[float]:
        key = "|".join(holes) + "|" + " ".join(board)
        if key not in self.data:
            self.data[key] = [float(e) for e in equity([parse_cards(h) for h in holes], parse_cards(" ".join(board)))]
            self.dirty = True
        return self.data[key]

    def save(self) -> None:
        if self.path and self.dirty:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=0))


def _all_in_take(hero: int, pot: int, fees: int, board: list[str], seats, actions, cache) -> float | None | str:
    """Hero's equity share of the pot after fees, in cents, if Hero was all-in before the river with cards shown.

    Returns None when the rule doesn't apply and "unshown" when it applies but a hand wasn't shown.
    """
    folded = {a.player for a in actions if a.action == "fold"}
    live = [p for p in seats if p not in folded]
    if hero not in live or len(live) < 2 or not any(a.all_in for a in actions):
        return None
    dealt_at_last_action = max(STREET_CARDS[a.street] for a in actions)
    if len(board) <= dealt_at_last_action:
        return None  # the betting reached the river (or the board was never dealt)
    if any(not seats[p].hole_cards or len(seats[p].hole_cards.split()) != 2 for p in live):
        return "unshown"
    known_board = board[:dealt_at_last_action]

    contributions = {p: s.invested for p, s in seats.items()}
    levels = sorted({contributions[p] for p in live})
    take, previous = 0.0, 0
    for i, level in enumerate(levels):
        top = max(contributions.values()) if i == len(levels) - 1 else level  # dead money above the top goes here
        layer = sum(min(c, top) - min(c, previous) for c in contributions.values())
        eligible = [p for p in live if contributions[p] >= level]
        if hero in eligible:
            if len(eligible) == 1:
                share = 1.0
            else:
                shares = cache.get([seats[p].hole_cards for p in eligible], known_board)
                share = shares[eligible.index(hero)]
            take += layer * share
        previous = level
    return take * (pot - fees) / pot


def hero_decisions(conn: sqlite3.Connection, equity_cache: Path | None = None) -> DecisionSet:
    out = DecisionSet()
    cache = _EquityCache(equity_cache)
    for hand_id, bb, pot, fees, board, seats, actions in _load(conn):
        out.hands_seen += 1
        hero = next(p for p, s in seats.items() if s.is_hero)
        position = {p: s.position for p, s in seats.items()}
        preflop = [a for a in actions if a.street == "preflop"]
        _count_opponent_open(preflop, hero, bb, out.opponent_open_sizes)

        if any(a.action == "straddle" for a in preflop):
            out.excluded["straddle in the hand"] += 1
            continue
        if any(a.player == hero and a.action == "post_dead" for a in preflop):
            out.excluded["Hero posted a missed (dead) blind"] += 1
            continue
        hero_posts = {a.action for a in preflop if a.player == hero and a.action.startswith("post_")}
        if ("post_bb" in hero_posts and position[hero] != "BB") or (
            "post_sb" in hero_posts and position[hero] not in ("SB", "BTN/SB")
        ):
            out.excluded["Hero posted a blind outside the blinds (joining the table)"] += 1
            continue

        take = _all_in_take(hero, pot, fees, board, seats, actions, cache)
        if take == "unshown":
            out.all_in_unshown += 1
        all_in_ev = isinstance(take, float)
        out.all_in_hands += all_in_ev
        hero_take = take if all_in_ev else seats[hero].collected

        chips = _chips_added(actions)
        hero_in_before = 0
        hero_chips_before = {}
        for a, c in zip(actions, chips):
            hero_chips_before[a.seq] = hero_in_before
            if a.player == hero:
                hero_in_before += c

        raises: list[_Action] = []
        limpers: list[int] = []
        callers: list[int] = []
        previous: Decision | None = None
        hero_raise_level: int | None = None  # raises before Hero's latest raise: 0 = open, 1 = 3-bet
        for a in preflop:
            if a.action.startswith("post_") or a.action == "straddle":
                continue
            if a.player == hero:
                situation, villain, other = _classify(position, hero, raises, limpers, callers, previous, hero_raise_level)
                faced = raises[-1].raise_to / bb if raises else None
                put_in_after = seats[hero].invested - hero_chips_before[a.seq]
                previous = Decision(
                    hand_id=hand_id,
                    situation=situation,
                    hero_position=position[hero],
                    villain_position=position[villain] if villain is not None else None,
                    hole_cards=seats[hero].hole_cards,
                    hand=hand_class(seats[hero].hole_cards),
                    group=hand_group(hand_class(seats[hero].hole_cards)),
                    action=a.action,
                    hero_all_in=a.all_in,
                    raise_to_bb=a.raise_to / bb if a.action == "raise" else None,
                    faced_bb=faced,
                    limpers=len(limpers),
                    callers=len(callers),
                    result_bb=(hero_take - put_in_after) / bb,
                    all_in_ev=all_in_ev,
                    other_kind=other,
                )
                out.decisions.append(previous)
                if a.action == "raise":
                    hero_raise_level = len(raises)
            if a.action == "raise":
                raises.append(a)
                callers = []
            elif a.action in ("call", "check"):
                (callers if raises else limpers).append(a.player)
    cache.save()
    return out


def _count_opponent_open(preflop: list[_Action], hero: int, bb: int, sizes: Counter) -> None:
    if any(a.action == "straddle" for a in preflop):
        return
    for a in preflop:
        if a.action in ("call", "check"):
            return  # limped pot: a raise now is an isolation raise, not an open
        if a.action == "raise":
            if a.player != hero:
                sizes[round(a.raise_to / bb, 2)] += 1
            return


def _classify(position, hero, raises, limpers, callers, previous, hero_raise_level):
    """Return (situation, villain player, description for 'other')."""
    hero_pos = position[hero]
    if previous is None:
        if not raises:
            if not limpers:
                return ("bvb" if hero_pos in ("SB", "BTN/SB") else "rfi"), None, None
            if hero_pos == "BB" and len(limpers) == 1 and position[limpers[0]] in ("SB", "BTN/SB"):
                return "bb_vs_sb_limp", limpers[0], None
            return "vs_limpers", None, None
        if len(raises) == 1:
            if limpers:
                return "other", raises[0].player, "facing a raise over limpers"
            return ("squeeze" if callers else "vs_open"), raises[0].player, None
        bet = len(raises) + 1
        return "other", raises[-1].player, f"facing a {bet}-bet{'+' if bet > 4 else ''} without having acted"

    after = len(raises) - 1 - hero_raise_level if previous.action == "raise" else None
    if previous.action == "raise" and after == 1:
        if hero_raise_level == 0 and previous.situation in ("rfi", "bvb"):
            return "vs_3bet", raises[-1].player, None
        if hero_raise_level == 1:
            return "vs_4bet", raises[-1].player, None
    if (
        previous.situation == "bvb"
        and previous.action == "call"
        and len(raises) == 1
        and position[raises[0].player] == "BB"
    ):
        return "sb_limp_vs_bb_raise", raises[0].player, None
    names = {0: "opening", 1: "3-betting", 2: "4-betting"}
    if previous.action == "raise":
        what = names.get(hero_raise_level, f"{hero_raise_level + 2}-betting")
        if hero_raise_level == 0 and previous.situation not in ("rfi", "bvb"):
            what = "raising over limpers"
        return "other", raises[-1].player, f"facing {after} re-raise(s) after {what}"
    verb = {"call": "limping" if previous.situation in ("vs_limpers", "bvb", "rfi") else "calling", "check": "checking"}
    return "other", raises[-1].player, f"facing a raise after {verb.get(previous.action, previous.action)}"
