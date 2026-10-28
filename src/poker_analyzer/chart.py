"""Compare Hero's preflop decisions with solver charts (charts/pokalab_6max.json).

Each compared decision is looked up in the chart for the exact hand Hero held. It is
"in line" when the chart takes Hero's action with that hand at least 10% of the time.
For a group of decisions, the expected count of an action is the sum of the chart's
frequencies for it over the hands Hero held, so mixed strategies are judged fairly,
and z = (actual - expected) / sqrt(sum of p(1-p)).
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import numpy as np

from . import settings
from .preflop import HAND_GROUPS, SIZE_BUCKETS, Decision, DecisionSet

CHART_PATH = settings.PROJECT_ROOT / "charts" / "pokalab_6max.json"

ACTIONS = {
    "rfi": ("raise", "call", "fold"),
    "vs_open": ("3bet", "call", "fold"),
    "vs_3bet": ("4bet", "allin", "call", "fold"),
}
KIND_NAMES = {
    "rfi": "RFI (folded to Hero)",
    "vs_open": "Facing a single open",
    "vs_3bet": "Facing a 3-bet after opening",
}
IN_LINE = 0.10  # the chart takes Hero's action at least this often with the hand
MIN_GROUP = 10  # decisions a spot or hand group needs before a deviation is flagged
MIN_HAND = 15  # the same for a single hand
MIN_STRENGTH = 30  # decisions a close match needs to count as a strength
STACKS_BB = (60, 150)  # effective stacks compared with the 100bb charts
NO_FLAT = ("HJ", "CO")  # the chart never flats an open from these seats
REASONS = ["squeeze", "limpers", "facing a 4-bet", "heads-up", "stack outside 60-150bb", "other"]
EPS = 1e-9

VERBS = {"raise": "open", "3bet": "3-bet", "4bet": "4-bet", "allin": "shove", "call": "call", "fold": "fold"}
BUCKET_PHRASES = {
    "min-raise (2bb)": "min-raise (2bb)",
    "small (2.1-2.9bb)": "2.1-2.9bb open",
    "3bb": "3bb open",
    "large (over 3bb)": "open over 3bb",
}


def verb(kind: str, action: str) -> str:
    return "limp" if (kind, action) == ("rfi", "call") else VERBS[action]


@dataclass
class Charts:
    spots: dict[tuple, dict[str, dict[str, float]]]  # spot -> hand -> action -> % of the time
    source: str = ""
    notes: list[str] = field(default_factory=list)

    def freqs(self, spot: tuple, hand: str) -> dict[str, float]:
        """The chart's probability of each action with this hand, fold included. Unlisted hands always fold."""
        given = {a: p / 100 for a, p in self.spots[spot].get(hand, {}).items()}
        total = sum(given.values())
        if total > 1:  # rounding in the source: a few hands add up to 100.1%
            given = {a: p / total for a, p in given.items()}
            total = 1.0
        out = {a: given.get(a, 0.0) for a in ACTIONS[spot[0]]}
        out["fold"] = 1 - total
        return out


def load_charts(path: Path = CHART_PATH) -> Charts:
    """Spots are ("rfi", seat), ("vs_open", hero, opener) and ("vs_3bet", opener, 3-bettor)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    c = raw["charts"]
    spots = {("rfi", p): v["hands"] for p, v in c["rfi"].items()}
    spots |= {("vs_open", h, o): v["hands"] for h, by in c["vs_open"].items() for o, v in by.items()}
    spots |= {("vs_3bet", o, t): v["hands"] for o, by in c["vs_3bet"].items() for t, v in by.items()}
    for spot, hands in spots.items():
        for hand, actions in hands.items():
            if unknown := set(actions) - set(ACTIONS[spot[0]]) | ({"fold"} & set(actions)):
                raise ValueError(f"{spot} {hand}: unexpected actions {sorted(unknown)}")
    return Charts(spots, raw.get("source", ""), raw.get("notes", []))


def true_bucket(spot: tuple) -> str | None:
    """The open-size bucket holding the open the chart assumes: 2.5bb, or 3bb from the SB."""
    if spot[0] != "vs_open":
        return None
    size = 3.0 if spot[2] == "SB" else 2.5
    return next(name for name, upper in SIZE_BUCKETS if size <= upper)


def spot_label(spot: tuple, bucket: str | None = None) -> str:
    kind = spot[0]
    if kind == "rfi":
        return f"{spot[1]} open"
    if kind == "vs_3bet":
        return f"{spot[1]} open vs {spot[2]} 3-bet"
    if bucket is None:
        return f"{spot[1]} vs {spot[2]} open"
    label = f"{spot[1]} vs {spot[2]} {BUCKET_PHRASES.get(bucket, bucket)}"
    return label if bucket == true_bucket(spot) else label + ", approximate"


@dataclass
class Compared:
    decision: Decision | None
    spot: tuple
    action: str  # Hero's action in chart terms
    freqs: dict[str, float]  # the chart's frequencies for the exact hand Hero held
    bucket: str | None = None  # open size faced, facing an open only

    @property
    def p(self) -> float:
        return self.freqs[self.action]

    @property
    def in_line(self) -> bool:
        return self.p >= IN_LINE

    @property
    def unit(self) -> tuple:
        return self.spot, self.bucket

    @property
    def approximate(self) -> bool:
        return self.bucket is not None and self.bucket != true_bucket(self.spot)


@dataclass
class Comparison:
    compared: list[Compared] = field(default_factory=list)  # scored against the chart
    off_chart_open: list[Compared] = field(default_factory=list)  # facing a 3-bet with a hand the RFI chart never opens
    no_flat: list[Compared] = field(default_factory=list)  # flats from HJ and CO, which the chart never makes
    skipped: Counter = field(default_factory=Counter)  # reason -> decisions
    skipped_by_situation: Counter = field(default_factory=Counter)  # (situation, reason) -> decisions
    other_detail: Counter = field(default_factory=Counter)  # what the "other" decisions were
    hands_dealt: int = 0


def effective_stack(d: Decision) -> float:
    """Hero vs the biggest other stack for RFI, otherwise Hero vs the opener or 3-bettor, in bb."""
    other = d.max_other_stack_bb if d.situation in ("rfi", "bvb") else d.villain_stack_bb
    return min(d.hero_stack_bb, other)


def chart_spot(d: Decision, charts: Charts) -> tuple[tuple | None, str | None, str | None]:
    """(spot, None, None) for a decision the charts cover, else (None, reason, detail)."""
    s, kind_of_other = d.situation, d.other_kind or ""
    if s == "squeeze":
        return None, "squeeze", None
    if s in ("vs_limpers", "bb_vs_sb_limp", "sb_limp_vs_bb_raise") or (s == "other" and "limp" in kind_of_other):
        return None, "limpers", None
    if s == "vs_4bet" or kind_of_other.startswith("facing a 4-bet"):
        return None, "facing a 4-bet", None
    if s not in ("rfi", "bvb", "vs_open", "vs_3bet"):
        return None, "other", kind_of_other
    if d.players < 3:
        return None, "heads-up", None
    if d.others_in:
        return None, "other", "a third player was in the pot"
    if d.faced_all_in:
        return None, "other", "the raise Hero faced was all-in"
    low, high = STACKS_BB
    if not low <= effective_stack(d) <= high:
        return None, "stack outside 60-150bb", None
    if s in ("rfi", "bvb"):
        spot = ("rfi", d.hero_position)
    else:
        spot = (s, d.hero_position, d.villain_position)
    if spot not in charts.spots:
        return None, "other", f"no chart for {spot_label(spot)}"
    return spot, None, None


def chart_action(kind: str, d: Decision) -> str:
    """Hero's action in chart terms: a limp is a call, a raise facing a 3-bet is a 4-bet or an all-in."""
    if d.basic_action != "raise":
        return d.basic_action
    if kind == "rfi":
        return "raise"
    if kind == "vs_open":
        return "3bet"
    return "allin" if d.hero_all_in or d.raise_to_bb > effective_stack(d) / 2 else "4bet"


def compare(ds: DecisionSet, charts: Charts) -> Comparison:
    out = Comparison(hands_dealt=ds.hands_seen)
    for d in ds.decisions:
        spot, reason, detail = chart_spot(d, charts)
        if spot is None:
            out.skipped[reason] += 1
            out.skipped_by_situation[(d.situation, reason)] += 1
            if reason == "other":
                out.other_detail[detail] += 1
            continue
        c = Compared(d, spot, chart_action(spot[0], d), charts.freqs(spot, d.hand), d.size_bucket)
        if spot[0] == "vs_3bet" and charts.freqs(("rfi", spot[1]), d.hand)["raise"] == 0:
            out.off_chart_open.append(c)
        elif spot[0] == "vs_open" and c.action == "call" and d.hero_position in NO_FLAT:
            out.no_flat.append(c)
        else:
            out.compared.append(c)
    return out


@dataclass
class ActionStats:
    n: int
    expected: float
    actual: int
    variance: float

    @property
    def diff(self) -> float:
        return self.actual - self.expected

    @property
    def z(self) -> float | None:
        """None when the variance is 0: every hand was one the chart plays 0% or 100%."""
        return self.diff / math.sqrt(self.variance) if self.variance > EPS else None

    def flagged(self, min_n: int = MIN_GROUP) -> bool:
        if self.n < min_n:
            return False
        return abs(self.diff) > EPS if self.z is None else abs(self.z) >= 2

    @property
    def close(self) -> bool:
        return abs(self.diff) <= EPS if self.z is None else abs(self.z) < 1


def action_stats(items: list[Compared], action: str) -> ActionStats:
    ps = [c.freqs[action] for c in items]
    return ActionStats(len(items), sum(ps), sum(c.action == action for c in items), sum(p * (1 - p) for p in ps))


@dataclass
class Group:
    unit: tuple  # (spot, bucket)
    level: str  # "spot", "group" or "hand"
    name: str | None  # the hand group or hand; None for the whole spot
    items: list[Compared]

    @property
    def spot(self) -> tuple:
        return self.unit[0]

    @property
    def n(self) -> int:
        return len(self.items)

    @cached_property
    def stats(self) -> dict[str, ActionStats]:
        return {a: action_stats(self.items, a) for a in ACTIONS[self.spot[0]]}

    @property
    def flagged(self) -> list[str]:
        min_n = MIN_HAND if self.level == "hand" else MIN_GROUP
        return [a for a, s in self.stats.items() if s.flagged(min_n)]

    @property
    def close(self) -> bool:
        return self.n >= MIN_STRENGTH and all(s.close for s in self.stats.values())

    @property
    def always_folded(self) -> bool:
        """Every hand here is one the chart always folds."""
        return all(c.freqs["fold"] >= 1 - EPS for c in self.items)

    def pct(self, action: str) -> tuple[float, float]:
        """Hero's and the chart's % for an action."""
        s = self.stats[action]
        return 100 * s.actual / s.n, 100 * s.expected / s.n


def groups(comparison: Comparison) -> list[Group]:
    """Every spot (open-size buckets apart), each hand group in it, and each hand in it."""
    by_unit = defaultdict(list)
    for c in comparison.compared:
        by_unit[c.unit].append(c)
    out = []
    for unit, items in by_unit.items():
        out.append(Group(unit, "spot", None, items))
        by_group, by_hand = defaultdict(list), defaultdict(list)
        for c in items:
            by_group[c.decision.group].append(c)
            by_hand[c.decision.hand].append(c)
        out += [Group(unit, "group", g, by_group[g]) for g in HAND_GROUPS if g in by_group]
        out += [Group(unit, "hand", h, hs) for h, hs in sorted(by_hand.items())]
    return out


def describe(g: Group) -> str:
    """How a hand group or hand is named in a sentence."""
    if g.name is None:
        return ""
    if g.level == "hand":
        return g.name
    return g.name[0].lower() + g.name[1:] + (" hands" if g.name in ("Other suited", "Other offsuit") else "")


def _num(x: float) -> str:
    return f"{x:.0f}" if x >= 9.95 else f"{x:.1f}" if x >= 0.095 else f"{x:.2f}"


@dataclass
class Leak:
    group: Group
    kind: str  # "too loose", "too tight" or "wrong action"
    action: str  # the action the numbers in the sentence are about
    per_1000: float  # extra (+) or missing (-) decisions with that action per 1,000 hands dealt
    sentence: str


def leak(g: Group, hands_dealt: int) -> Leak | None:
    """One plain sentence for a flagged deviation, or None if nothing is flagged."""
    if not g.flagged:
        return None
    kind_ = g.spot[0]
    diff = {a: s.diff for a, s in g.stats.items()}
    main = max(g.flagged, key=lambda a: abs(diff[a]))
    other = min(diff, key=diff.get) if diff[main] > 0 else max(diff, key=diff.get)
    over, under = (main, other) if diff[main] > 0 else (other, main)
    if under == "fold":
        kind, action = "too loose", over
    elif over == "fold":
        kind, action = "too tight", under
    else:
        kind, action = "wrong action", over
    per_1000 = diff[action] * 1000 / hands_dealt
    amount = (f"+{_num(per_1000)} extra" if per_1000 > 0 else f"{_num(-per_1000)} fewer") + f" {verb(kind_, action)}s"
    what = describe(g)
    hands = f" {what}" if what else ""
    you, chart = g.pct(action)
    if kind == "wrong action":
        you_u, chart_u = g.pct(under)
        text = (
            f"you {verb(kind_, over)}{hands} where the chart {verb(kind_, under)}s: {verb(kind_, over)} {you:.0f}% vs "
            f"{chart:.0f}%, {verb(kind_, under)} {you_u:.0f}% vs {chart_u:.0f}% ({amount} per 1,000 hands)."
        )
    else:
        only = "only " if per_1000 < 0 else ""
        text = (
            f"you {verb(kind_, action)}{hands} {only}{you:.0f}% of the time vs {chart:.0f}% for the chart "
            f"({amount} per 1,000 hands)."
        )
    return Leak(g, kind, action, per_1000, f"{spot_label(*g.unit)}, {kind}: {text}")


def strength(g: Group) -> str:
    """One plain sentence for a close match: Hero's % vs the chart's for every action either takes."""
    kind_ = g.spot[0]
    parts = []
    for a in ACTIONS[kind_]:
        if g.stats[a].actual or g.stats[a].expected > EPS:
            you, chart = g.pct(a)
            parts.append(f"{verb(kind_, a)} {you:.0f}% vs {chart:.0f}%")
    return f"{spot_label(*g.unit)}, {describe(g) or 'all hands'}: you {', '.join(parts)} for the chart ({g.n} decisions)."


def top_leaks(all_groups: list[Group], hands_dealt: int, limit: int | None = 10) -> list[Leak]:
    """Flagged hand groups, biggest extra or missing decisions per 1,000 hands first."""
    leaks = [l for g in all_groups if g.level == "group" and (l := leak(g, hands_dealt))]
    leaks.sort(key=lambda l: -abs(l.per_1000))
    return leaks[:limit] if limit else leaks


def strengths(all_groups: list[Group]) -> tuple[list[Group], int]:
    """Spots and hand groups that match the chart closely, plus how many matches are hands the chart always folds."""
    close = [g for g in all_groups if g.level in ("spot", "group") and g.close]
    trivial = [g for g in close if g.level == "group" and g.always_folded]
    kept = [g for g in close if g not in trivial]
    kept.sort(key=lambda g: (g.level != "spot", -g.n))
    return kept, len(trivial)


@dataclass
class Result:
    n: int
    mean: float
    low: float
    high: float


def bootstrap(items: list[Compared], reps: int = 2000, seed: int = 0) -> Result | None:
    """Mean result in bb per decision with a 95% interval, resampling whole sessions."""
    if not items:
        return None
    values = np.array([c.decision.result_bb for c in items])
    _, session = np.unique([c.decision.session_id for c in items], return_inverse=True)
    sums, counts = np.bincount(session, weights=values), np.bincount(session)
    pick = np.random.default_rng(seed).integers(0, len(sums), size=(reps, len(sums)))
    means = sums[pick].sum(axis=1) / counts[pick].sum(axis=1)
    low, high = np.percentile(means, [2.5, 97.5])
    return Result(len(items), float(values.mean()), float(low), float(high))


def deviation_results(g: Group, all_groups_by_key: dict) -> tuple[Result | None, Result | None]:
    """Results of the off-chart decisions in a flagged group, and of the in-line decisions with the same
    hand group in the same spot (the whole spot for a spot-level deviation)."""
    off = [c for c in g.items if not c.in_line]
    if g.level == "hand":
        same = all_groups_by_key[(g.unit, "group", g.items[0].decision.group)].items
    else:
        same = g.items
    return bootstrap(off), bootstrap([c for c in same if c.in_line])
