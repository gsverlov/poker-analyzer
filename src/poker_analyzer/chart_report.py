"""Write the chart comparison report: reports/preflop_vs_chart.html, one self-contained file.

    python -m poker_analyzer.chart_report
"""

from __future__ import annotations

import argparse
import html
import sys
from collections import Counter, defaultdict
from pathlib import Path

from . import db, settings
from .chart import (
    ACTIONS, CHART_PATH, IN_LINE, KIND_NAMES, MIN_GROUP, MIN_HAND, MIN_STRENGTH, REASONS, STACKS_BB, Charts,
    Comparison, Group, Result, bootstrap, compare, deviation_results, groups, load_charts, spot_label,
    strength, strengths, top_leaks, true_bucket, verb,
)
from .preflop import SITUATIONS, SIZE_BUCKETS, hero_decisions
from .preflop_report import STYLE as BASE_STYLE
from .preflop_report import _hand_name, report_meta

REPORT_PATH = settings.PROJECT_ROOT / "reports" / "preflop_vs_chart.html"
SEATS = ["UTG", "HJ", "CO", "BTN", "SB", "BB"]
COLOUR = {"raise": "a", "3bet": "a", "4bet": "a", "allin": "s", "call": "c"}  # fold fills the rest


def _e(text) -> str:
    return html.escape(str(text))


def _bb(r: Result | None) -> str:
    if r is None:
        return '<span class="muted">-</span>'
    cls = "pos" if r.mean > 0.005 else "neg" if r.mean < -0.005 else ""
    return f'<span class="{cls}">{r.mean:+.2f}</span> <span class="ci">[{r.low:+.2f}, {r.high:+.2f}]</span> <span class="muted">({r.n})</span>'


def _z(z: float | None) -> str:
    return "pure" if z is None else f"{z:+.1f}"


def _spot_order(spot: tuple) -> tuple:
    return (list(ACTIONS).index(spot[0]), *(SEATS.index(p) for p in spot[1:]))


def _bucket_order(spot: tuple, bucket: str | None) -> int:
    names = [b for b, _ in SIZE_BUCKETS]
    return -1 if bucket == true_bucket(spot) else names.index(bucket) if bucket in names else 0


# ---- grids ----

def _cell(name: str, shares: dict[str, float], tip: str, extra: str = "", label: str = "") -> str:
    parts = Counter()
    for a, p in shares.items():
        if a in COLOUR:
            parts[COLOUR[a]] += 100 * p
    style = ";".join(f"--{k}:{v:.1f}" for k, v in parts.items() if v)
    return f'<div class="cell{extra}" style="{style}" title="{_e(tip)}"><b>{name}</b>{label}</div>'


def _shares_text(kind: str, shares: dict[str, float], digits: int = 0) -> str:
    return ", ".join(f"{verb(kind, a)} {100 * p:.{digits}f}%" for a, p in shares.items() if p > 0.0005)


def hero_grid(g: Group, by_hand: dict[str, Group]) -> str:
    kind = g.spot[0]
    out = ['<div class="grid">']
    for row in range(13):
        for col in range(13):
            name = _hand_name(row, col)
            h = by_hand.get(name)
            if not h:
                out.append(f'<div class="cell empty" title="{name}: never dealt here"><b>{name}</b></div>')
                continue
            you = {a: s.actual / h.n for a, s in h.stats.items()}
            chart = {a: s.expected / h.n for a, s in h.stats.items()}
            counts = ", ".join(f"{verb(kind, a)} {s.expected:.1f}/{s.actual}" for a, s in h.stats.items())
            tip = (f"{name}: {h.n} decisions. You: {_shares_text(kind, you)}. Chart: {_shares_text(kind, chart, 1)}."
                   f" Expected/actual: {counts}.")
            flagged = h.flagged
            if flagged:
                tip += " Flagged: " + ", ".join(f"{verb(kind, a)} z {_z(h.stats[a].z)}" for a in flagged) + "."
            extra = (" faint" if h.n < 3 else "") + (" flag" if flagged else "")
            out.append(_cell(name, you, tip, extra, f"<i>{h.n}</i>"))
    out.append("</div>")
    return "".join(out)


def chart_grid(charts: Charts, spot: tuple) -> str:
    kind = spot[0]
    out = ['<div class="grid">']
    for row in range(13):
        for col in range(13):
            name = _hand_name(row, col)
            if kind == "vs_3bet" and charts.freqs(("rfi", spot[1]), name)["raise"] == 0:
                out.append(f'<div class="cell empty" title="{name}: never opened from {spot[1]}"><b>{name}</b></div>')
                continue
            shares = charts.freqs(spot, name)
            out.append(_cell(name, shares, f"{name}: {_shares_text(kind, shares, 1)}."))
    out.append("</div>")
    return "".join(out)


def legend(kind: str) -> str:
    var = {"a": "--raise", "s": "--allin", "c": "--call"}
    items = "".join(
        f'<span style="--c:var({var[COLOUR[a]] if a in COLOUR else "--fold"})">{verb(kind, a).capitalize()}</span>'
        for a in ACTIONS[kind]
    )
    return f'<div class="legend">{items}</div>'


# ---- tables ----

def group_table(unit_groups: list[Group], by_key: dict) -> str:
    kind = unit_groups[0].spot[0]
    actions = ACTIONS[kind]
    rows = []
    for g in unit_groups:
        first = True
        flagged = g.flagged
        if flagged:
            off, same = deviation_results(g, by_key)
            result = f"Off-chart: {_bb(off)}<br>In line: {_bb(same)}"
        else:
            result = _bb(bootstrap(g.items))
        in_line = sum(c.in_line for c in g.items)
        name = "All hands" if g.name is None else g.name
        badge = ' <span class="badge good">close match</span>' if g.close else ""
        for a in actions:
            s = g.stats[a]
            you, chart = g.pct(a)
            flag = ""
            if a in flagged:
                flag = f'<span class="badge bad">{"more" if s.diff > 0 else "less"} than chart</span>'
            cells = (
                f"<td>{verb(kind, a)}</td><td>{you:.0f}%</td><td>{chart:.0f}%</td><td>{s.expected:.1f}</td>"
                f"<td>{s.actual}</td><td>{s.diff + 0.0:+.1f}</td><td>{_z(s.z)}</td><td class='left'>{flag}</td>"
            )
            if first:
                span = f' rowspan="{len(actions)}"'
                cls = ' class="total first"' if g.name is None else ' class="first"'
                rows.append(
                    f"<tr{cls}><th{span}>{_e(name)}{badge}</th><td{span}>{g.n}</td>"
                    f"<td{span}>{100 * in_line / g.n:.0f}%</td>{cells}<td{span} class='left'>{result}</td></tr>"
                )
                first = False
            else:
                rows.append(f"<tr>{cells}</tr>")
    return (
        '<div class="table-wrap"><table class="cmp"><thead><tr><th>Hand group</th><th>Decisions</th><th>In line</th>'
        "<th>Action</th><th>You</th><th>Chart</th><th>Expected</th><th>Actual</th><th>Diff</th><th>z</th><th>Flag</th>"
        "<th>Your result, bb per decision<br>[95% CI by session] (info only)</th></tr></thead>"
        f'<tbody>{"".join(rows)}</tbody></table></div>'
    )


def hand_table(hands: list[Group], by_key: dict) -> str:
    hands = [h for h in hands if h.n >= MIN_HAND]
    if not hands:
        return f'<p class="muted">No single hand came up {MIN_HAND} times here.</p>'
    kind = hands[0].spot[0]
    rows = []
    for h in sorted(hands, key=lambda h: -h.n):
        you = {a: s.actual / h.n for a, s in h.stats.items()}
        chart = {a: s.expected / h.n for a, s in h.stats.items()}
        flags = ", ".join(f"{verb(kind, a)} {'more' if h.stats[a].diff > 0 else 'less'} (z {_z(h.stats[a].z)})" for a in h.flagged)
        badge = f'<span class="badge bad">{flags}</span>' if flags else ""
        if h.flagged:
            off, same = deviation_results(h, by_key)
            result = f"Off-chart: {_bb(off)}<br>In line, same hand group: {_bb(same)}"
        else:
            result = _bb(bootstrap(h.items))
        rows.append(
            f"<tr><th>{h.name}</th><td>{h.n}</td><td class='left'>{_shares_text(kind, you)}</td>"
            f"<td class='left'>{_shares_text(kind, chart, 1)}</td>"
            f"<td class='left'>{badge}</td>"
            f"<td class='left'>{result}</td></tr>"
        )
    return (
        f'<div class="table-wrap"><table class="cmp"><thead><tr><th>Hand</th><th>Decisions</th><th>You</th><th>Chart</th>'
        f"<th>Flag</th><th>Your result, bb [95% CI] (info only)</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def unit_block(unit: tuple, all_groups: list[Group], by_key: dict, charts: Charts) -> str:
    spot, bucket = unit
    mine = [g for g in all_groups if g.unit == unit]
    whole = next(g for g in mine if g.level == "spot")
    hand_groups = [g for g in mine if g.level == "group"]
    by_hand = {g.name: g for g in mine if g.level == "hand"}
    in_line = sum(c.in_line for c in whole.items)
    note = ""
    if bucket is not None:
        note = (" <span class='badge good'>true comparison</span>" if bucket == true_bucket(spot)
                else " <span class='badge warn'>approximate: the chart assumes a 2.5bb open</span>")
    title = f"Open size faced: {bucket}" if bucket else "All decisions"
    return (
        f"<div class='unit'><h4>{_e(title)}{note} <span class='count'>{whole.n} decisions, "
        f"{100 * in_line / whole.n:.0f}% in line</span></h4>"
        f"<div class='pair'><div><h5>You</h5>{hero_grid(whole, by_hand)}</div>"
        f"<div><h5>Chart</h5>{chart_grid(charts, spot)}</div></div>"
        f"{group_table(hand_groups + [whole], by_key)}"
        f"<details class='inner'><summary>Single hands with at least {MIN_HAND} decisions</summary>"
        f"{hand_table(list(by_hand.values()), by_key)}</details></div>"
    )


def spots_section(comparison: Comparison, all_groups: list[Group], by_key: dict, charts: Charts) -> str:
    units = defaultdict(list)
    for g in all_groups:
        if g.level == "spot":
            units[g.spot].append(g)
    out = ['<section id="spots"><h2>Spot by spot</h2>',
           "<p class='muted'>Each square shows how often that hand takes each action, in the same colours for you and "
           "the chart; hover for the numbers. Outlined squares are single hands flagged with at least "
           f"{MIN_HAND} decisions; faded squares came up once or twice.</p>"]
    for kind in ACTIONS:
        out.append(f"<h3>{_e(KIND_NAMES[kind])}</h3>{legend(kind)}")
        for spot in sorted((s for s in charts.spots if s[0] == kind), key=_spot_order):
            spot_units = sorted(units.get(spot, []), key=lambda g: _bucket_order(spot, g.unit[1]))
            n = sum(g.n for g in spot_units)
            if not n:
                out.append(f"<p class='empty-spot'>{_e(spot_label(spot))} <span class='count'>no decisions</span></p>")
                continue
            in_line = sum(c.in_line for g in spot_units for c in g.items)
            flagged = sum(1 for g in all_groups if g.spot == spot and g.level == "group" and g.flagged)
            flag_note = f", {flagged} flagged hand group{'s' * (flagged != 1)}" if flagged else ""
            out.append(
                f"<details class='spot'><summary>{_e(spot_label(spot))} <span class='count'>{n} decisions, "
                f"{100 * in_line / n:.0f}% in line{flag_note}</span></summary>"
                + "".join(unit_block(g.unit, all_groups, by_key, charts) for g in spot_units)
                + "</details>"
            )
    out.append("</section>")
    return "".join(out)


# ---- top of the report ----

def overall_section(comparison: Comparison) -> str:
    rows, total, total_in = [], 0, 0
    for kind, name in KIND_NAMES.items():
        cs = [c for c in comparison.compared if c.spot[0] == kind]
        n_in = sum(c.in_line for c in cs)
        total, total_in = total + len(cs), total_in + n_in
        rows.append(f"<tr><th>{_e(name)}</th><td>{len(cs):,}</td><td>{n_in:,}</td><td>{100 * n_in / len(cs):.0f}%</td></tr>")
    rows.append(f"<tr class='total'><th>All compared</th><td>{total:,}</td><td>{total_in:,}</td><td>{100 * total_in / total:.0f}%</td></tr>")
    skipped = sum(comparison.skipped.values())
    return f"""<section id="overall"><h2>Overall</h2>
<p>A decision is <b>in line</b> when the chart takes your action with that exact hand at least {IN_LINE:.0%} of the time.</p>
<div class="table-wrap"><table><thead><tr><th>Situation</th><th>Compared</th><th>In line</th><th>% in line</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<p class="muted">Not scored: {len(comparison.off_chart_open)} facing-a-3-bet decisions with a hand the chart never opens
(<a href="#off-open">off-chart at the open</a>), and {len(comparison.no_flat)} flats from HJ and CO, where
<a href="#no-flat">the chart has no call option</a>. {skipped:,} decisions <a href="#not-compared">couldn't be compared</a>.</p>
</section>"""


def leaks_section(leaks, by_key) -> str:
    items = []
    for lk in leaks:
        g = lk.group
        off, same = deviation_results(g, by_key)
        zs = ", ".join(
            f"{verb(g.spot[0], a)} (pure spot)" if g.stats[a].z is None else f"{verb(g.spot[0], a)} z {g.stats[a].z:+.1f}"
            for a in g.flagged
        )
        items.append(
            f"<li><p>{_e(lk.sentence)}</p><p class='meta'>{g.n} decisions · {zs} · Results (information only): "
            f"off-chart decisions {_bb(off)}; in line {_bb(same)}</p></li>"
        )
    return f"""<section id="leaks"><h2>Top leaks</h2>
<p class="muted">Hand groups within a spot (at least {MIN_GROUP} decisions) where you take an action more or less often than
the chart would with the same cards: |z| ≥ 2, or any difference where the chart plays every one of those hands 0% or 100%.
Ranked by extra or missing decisions per 1,000 hands dealt. Results are in bb per decision with a 95% interval from resampling
sessions; they are noisy, so treat them as information only.</p>
<ol class="leaks">{''.join(items) or '<li>No flagged deviations.</li>'}</ol></section>"""


def strengths_section(close: list[Group], trivial: int) -> str:
    shown, rest = close[:10], close[10:]
    more = ""
    if rest:
        more = (f"<details><summary>{len(rest)} more</summary><ul>"
                + "".join(f"<li>{_e(strength(g))}</li>" for g in rest) + "</ul></details>")
    folded = (f"<p class='muted'>Also {trivial} hand groups the chart always folds in a spot, which you fold every time too.</p>"
              if trivial else "")
    return f"""<section id="strengths"><h2>Strengths</h2>
<p class="muted">Spots and hand groups with at least {MIN_STRENGTH} decisions where every action is within one standard
deviation of the chart (|z| &lt; 1).</p>
<ul class="strengths">{''.join(f'<li>{_e(strength(g))}</li>' for g in shown) or '<li>None yet.</li>'}</ul>{more}{folded}</section>"""


def no_flat_section(comparison: Comparison) -> str:
    by_spot = defaultdict(list)
    for c in comparison.no_flat:
        by_spot[(c.spot, c.bucket)].append(c)
    rows = []
    for (spot, bucket), cs in sorted(by_spot.items(), key=lambda kv: (_spot_order(kv[0][0]), _bucket_order(*kv[0]))):
        hands = Counter(c.decision.hand for c in cs).most_common(6)
        rows.append(
            f"<tr><th>{_e(spot_label(spot, bucket))}</th><td>{len(cs)}</td>"
            f"<td class='left'>{', '.join(f'{h} ×{n}' for h, n in hands)}</td><td class='left'>{_bb(bootstrap(cs))}</td></tr>"
        )
    total = f"<tr class='total'><th>All</th><td>{len(comparison.no_flat)}</td><td></td><td class='left'>{_bb(bootstrap(comparison.no_flat))}</td></tr>"
    return f"""<section id="no-flat"><h2>Flats from HJ and CO: chart has no call option here</h2>
<p class="muted">In this solution HJ and CO only 3-bet or fold against an open, so these calls have nothing to be compared with.
They are listed here and not counted as leaks.</p>
<div class="table-wrap"><table><thead><tr><th>Spot</th><th>Flats</th><th>Most common hands</th>
<th>Your result, bb [95% CI] (info only)</th></tr></thead><tbody>{''.join(rows)}{total}</tbody></table></div></section>"""


def off_open_section(comparison: Comparison) -> str:
    rows = "".join(
        f"<tr><th>{_e(spot_label(c.spot))}</th><td>{c.decision.hand}</td><td>{verb('vs_3bet', c.action)}</td>"
        f"<td>{c.decision.result_bb:+.2f}</td></tr>"
        for c in sorted(comparison.off_chart_open, key=lambda c: (_spot_order(c.spot), c.decision.hand))
    )
    return f"""<section id="off-open"><h2>Facing a 3-bet: off-chart at the open</h2>
<p class="muted">You opened a hand the RFI chart never opens from that seat, so the chart has no answer for the 3-bet.
These decisions aren't scored.</p>
<div class="table-wrap"><table><thead><tr><th>Spot</th><th>Hand</th><th>Your action</th><th>Result, bb</th></tr></thead>
<tbody>{rows or '<tr><td colspan="4">None</td></tr>'}</tbody></table></div></section>"""


def not_compared_section(comparison: Comparison) -> str:
    reasons = "".join(f"<tr><th>{_e(r)}</th><td>{comparison.skipped[r]:,}</td></tr>" for r in REASONS if comparison.skipped[r])
    reasons += f"<tr class='total'><th>All</th><td>{sum(comparison.skipped.values()):,}</td></tr>"
    by_sit = "".join(
        f"<tr><th>{_e(SITUATIONS[s])}</th><td>{_e(r)}</td><td>{n:,}</td></tr>"
        for (s, r), n in sorted(comparison.skipped_by_situation.items(), key=lambda kv: (list(SITUATIONS).index(kv[0][0]), -kv[1]))
    )
    other = "".join(f"<tr><th>{_e(k)}</th><td>{n:,}</td></tr>" for k, n in comparison.other_detail.most_common())
    low, high = STACKS_BB
    return f"""<section id="not-compared"><h2>Not compared</h2>
<p>The charts cover three spots: folded to you, facing a single open with nobody else in, and facing a single 3-bet after
opening first-in with nobody else in. They also need at least 3 players dealt in and an effective stack of {low}-{high}bb
(for RFI, your stack vs the biggest other stack; facing an open, you vs the opener; facing a 3-bet, you vs the 3-bettor).</p>
<div class="cols"><div><h3>By reason</h3><div class="table-wrap"><table><thead><tr><th>Reason</th><th>Decisions</th></tr></thead>
<tbody>{reasons}</tbody></table></div></div>
<div><h3>"Other" in detail</h3><div class="table-wrap"><table><thead><tr><th>Spot</th><th>Decisions</th></tr></thead>
<tbody>{other or '<tr><td colspan="2">None</td></tr>'}</tbody></table></div></div></div>
<h3>By situation</h3><div class="table-wrap"><table><thead><tr><th>Situation</th><th>Reason</th><th>Decisions</th></tr></thead>
<tbody>{by_sit}</tbody></table></div></section>"""


def method_section(charts: Charts) -> str:
    notes = "".join(f"<li>{_e(n)}</li>" for n in charts.notes)
    return f"""<details class="method"><summary>How the comparison works</summary>
<p>Every decision is compared with the chart's frequencies for the exact hand you held: a hand the chart doesn't list is
always folded. For a group of decisions, the <b>expected</b> count of an action is the sum of the chart's frequencies for it
over those hands, and <b>actual</b> is how often you took it. z = (actual − expected) / √(Σ p(1−p)). A group is flagged at
|z| ≥ 2 with at least {MIN_GROUP} decisions ({MIN_HAND} for a single hand); where the variance is 0 (the chart plays every one of
those hands 0% or 100%), any difference is flagged ("pure" in the z column).</p>
<p>Your actions map to the chart's: in RFI a limp is a call; facing an open a raise is a 3-bet; facing a 3-bet a raise is a
4-bet, or all-in if it was all-in or more than half the effective stack. Facing an open, results are split by the open size you
faced. Only the bucket holding the size the chart assumes (2.5bb, or 3bb from the SB) is a true comparison.</p>
<p>Results are what you got back from that decision on, in bb, with all-ins before the river valued by equity (as in the
preflop report). Off-chart decisions are those where the chart takes your action less than {IN_LINE:.0%} of the time with that hand.</p>
<p>Chart: {_e(charts.source)}.</p><ul>{notes}</ul></details>"""


STYLE = BASE_STYLE + """
:root{--allin:#7b3fa0;--warn:#a86b00}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--warn:#e0a640}}
:root[data-theme="dark"]{--warn:#e0a640}
.pair{display:flex;flex-wrap:wrap;gap:12px 24px;margin:8px 0 12px}.pair>div{flex:1 1 320px;max-width:520px;min-width:0}
.pair .grid{min-width:0;max-width:520px;grid-template-columns:repeat(13,1fr);gap:1px}
.pair .cell{font-size:10px}.pair .cell i{font-size:9px}
.cell{background:linear-gradient(to right,var(--raise) calc(var(--a,0)*1%),var(--allin) 0 calc((var(--a,0) + var(--s,0))*1%),
var(--call) 0 calc((var(--a,0) + var(--s,0) + var(--c,0))*1%),var(--fold) 0)}
.cell.flag{outline:2px solid var(--text);outline-offset:-2px}
h4{font-size:14px;margin:16px 0 4px}h5{font-size:13px;margin:0 0 4px;color:var(--muted);font-weight:500}
.badge{display:inline-block;font-size:11px;padding:0 6px;border-radius:8px;border:1px solid currentColor;white-space:nowrap}
.badge.bad{color:var(--neg)}.badge.good{color:var(--pos)}.badge.warn{color:var(--warn)}
.ci{color:var(--muted);font-size:12px}table.cmp tr.first>*{border-top:2px solid var(--line)}
ol.leaks li{margin:0 0 10px}ol.leaks p{margin:0}.meta{color:var(--muted);font-size:12.5px}
ul.strengths li{margin:0 0 4px}details.spot>summary{font-size:14px}details.inner{margin:8px 0}
.unit{border-top:1px solid var(--line);margin-top:8px}.unit:first-of-type{border-top:0}
.empty-spot{margin:4px 0 4px 12px;color:var(--muted)}details.method{margin:16px 0}
"""


def build_html(comparison: Comparison, charts: Charts, meta: dict) -> str:
    all_groups = groups(comparison)
    by_key = {(g.unit, g.level, g.name): g for g in all_groups}
    leaks = top_leaks(all_groups, comparison.hands_dealt)
    close, trivial = strengths(all_groups)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Preflop vs chart</title><style>{STYLE}</style></head>
<body><main><h1>Preflop vs chart</h1>
<p class="muted">{comparison.hands_dealt:,} hands dealt, {meta['first']} to {meta['last']}, compared with the Pokalab 6-max
100bb solution. Generated {meta['generated']} from {_e(meta['db'])}.</p>
<nav><a href="#overall">Overall</a><a href="#leaks">Top leaks</a><a href="#strengths">Strengths</a>
<a href="#no-flat">HJ/CO flats</a><a href="#off-open">Off-chart at the open</a><a href="#spots">Spot by spot</a>
<a href="#not-compared">Not compared</a></nav>
{overall_section(comparison)}{leaks_section(leaks, by_key)}{strengths_section(close, trivial)}{method_section(charts)}
{spots_section(comparison, all_groups, by_key, charts)}{no_flat_section(comparison)}{off_open_section(comparison)}
{not_compared_section(comparison)}</main></body></html>
"""


def summary_text(comparison: Comparison) -> str:
    all_groups = groups(comparison)
    lines = ["Compared decisions:"]
    for kind, name in KIND_NAMES.items():
        cs = [c for c in comparison.compared if c.spot[0] == kind]
        lines.append(f"  {name}: {len(cs)} ({100 * sum(c.in_line for c in cs) / len(cs):.1f}% in line)")
    total = len(comparison.compared)
    lines.append(f"  All: {total} ({100 * sum(c.in_line for c in comparison.compared) / total:.1f}% in line)")
    lines.append(f"  Not scored: {len(comparison.off_chart_open)} off-chart at the open, {len(comparison.no_flat)} HJ/CO flats")
    lines.append("Not compared:")
    lines += [f"  {r}: {comparison.skipped[r]}" for r in REASONS]
    lines.append("Top leaks:")
    lines += [f"  {i}. {lk.sentence}" for i, lk in enumerate(top_leaks(all_groups, comparison.hands_dealt), 1)]
    close, trivial = strengths(all_groups)
    lines.append(f"Strengths ({len(close)}, plus {trivial} always-folded hand groups):")
    lines += [f"  - {strength(g)}" for g in close[:10]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Write the preflop vs chart report.")
    ap.add_argument("--db", default=settings.DB_PATH, type=Path)
    ap.add_argument("--chart", default=CHART_PATH, type=Path)
    ap.add_argument("--out", default=REPORT_PATH, type=Path)
    args = ap.parse_args(argv)
    charts = load_charts(args.chart)
    conn = db.connect(args.db)
    try:
        comparison = compare(hero_decisions(conn, settings.DATA_DIR / "equity_cache.json"), charts)
        meta = report_meta(conn, args.db)
    finally:
        conn.close()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build_html(comparison, charts, meta), encoding="utf-8")
    print(summary_text(comparison))
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
