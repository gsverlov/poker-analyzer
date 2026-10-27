"""Write the preflop report: reports/preflop.html, one self-contained file.

    python -m poker_analyzer.preflop_report
"""

from __future__ import annotations

import argparse
import html
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from . import db, settings
from .preflop import HAND_GROUPS, RANKS, SITUATIONS, SIZE_BUCKETS, Decision, DecisionSet, hero_decisions

MIN_GRID = 50  # decisions needed before a split gets its own grid
ACTIONS = ("raise", "call", "fold")
POSITIONS = ["UTG", "UTG+1", "UTG+2", "HJ", "CO", "BTN", "SB", "BB", "BTN/SB"]
REPORT_PATH = settings.PROJECT_ROOT / "reports" / "preflop.html"

# How each situation is split into smaller grids.
SPLITS = {
    "rfi": ["position"],
    "bvb": ["position"],
    "vs_open": ["pairing", "bucket", "pairing+bucket"],
    "squeeze": ["pairing", "bucket"],
    "vs_limpers": ["position"],
    "vs_3bet": ["in_position", "pairing"],
    "vs_4bet": ["in_position", "pairing"],
    "bb_vs_sb_limp": ["pairing"],
    "sb_limp_vs_bb_raise": ["pairing"],
}
CALL_LABEL = {"rfi": "Limp", "bvb": "Limp", "bb_vs_sb_limp": "Check"}


def _e(text) -> str:
    return html.escape(str(text))


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}%" if whole else ""


def _bb(total: float, n: int) -> str:
    if not n:
        return '<span class="muted">-</span>'
    value = total / n
    cls = "pos" if value > 0.005 else "neg" if value < -0.005 else ""
    return f'<span class="{cls}">{value:+.2f}</span>'


def _pos_key(p: str | None) -> int:
    return POSITIONS.index(p) if p in POSITIONS else len(POSITIONS)


class _Stats:
    def __init__(self):
        self.n = 0
        self.count = Counter()
        self.result = Counter()  # action -> summed bb

    def add(self, d: Decision) -> None:
        self.n += 1
        self.count[d.basic_action] += 1
        self.result[d.basic_action] += d.result_bb

    @property
    def total(self) -> float:
        return sum(self.result.values())


def _by(decisions, key) -> dict:
    stats = defaultdict(_Stats)
    for d in decisions:
        stats[key(d)].add(d)
    return stats


def _hand_name(row: int, col: int) -> str:
    a, b = RANKS[row], RANKS[col]
    if row == col:
        return a + b
    return a + b + "s" if col > row else b + a + "o"


def grid_html(decisions: list[Decision], situation: str) -> str:
    cells = _by(decisions, lambda d: d.hand)
    call = CALL_LABEL.get(situation, "Call")
    out = ['<div class="grid-wrap"><div class="grid">']
    for row in range(13):
        for col in range(13):
            name = _hand_name(row, col)
            s = cells.get(name)
            if not s:
                out.append(f'<div class="cell empty" title="{name}: never dealt here"><b>{name}</b></div>')
                continue
            r, c = (100 * s.count[a] / s.n for a in ("raise", "call"))
            tip = (
                f"{name}: {s.n} times. Raise {r:.0f}%, {call.lower()} {c:.0f}%, fold {100 - r - c:.0f}%."
                + "".join(
                    f" Avg if {a}: {s.result[a] / s.count[a]:+.2f}bb." for a in ("raise", "call") if s.count[a]
                )
            )
            style = (
                f"background:linear-gradient(to right,var(--raise) 0 {r:.1f}%,var(--call) {r:.1f}% {r + c:.1f}%,"
                f"var(--fold) {r + c:.1f}% 100%)"
            )
            faint = " faint" if s.n < 3 else ""
            out.append(f'<div class="cell{faint}" style="{style}" title="{_e(tip)}"><b>{name}</b><i>{s.n}</i></div>')
    out.append("</div></div>")
    out.append(group_table(decisions, call))
    return "".join(out)


def group_table(decisions: list[Decision], call: str) -> str:
    groups = _by(decisions, lambda d: d.group)
    rows = []
    for g in HAND_GROUPS + ["All hands"]:
        s = groups.get(g) if g != "All hands" else _by(decisions, lambda d: 0)[0]
        if not s:
            continue
        cls = ' class="total"' if g == "All hands" else ""
        rows.append(
            f"<tr{cls}><th>{_e(g)}</th><td>{s.n}</td>"
            + "".join(f"<td>{_pct(s.count[a], s.n)}</td>" for a in ACTIONS)
            + "".join(f"<td>{_bb(s.result[a], s.count[a])}</td>" for a in ("raise", "call"))
            + f"<td>{_bb(s.total, s.n)}</td></tr>"
        )
    return (
        '<div class="table-wrap"><table class="groups"><thead><tr><th>Hand group</th><th>Times</th>'
        f"<th>Raise</th><th>{call}</th><th>Fold</th><th>Avg bb if raise</th><th>Avg bb if {call.lower()}</th>"
        f'<th>Avg bb, all</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )


def _split_key(kind: str):
    if kind == "position":
        return lambda d: d.hero_position, lambda k: f"Hero {k}", lambda k: _pos_key(k)
    if kind == "pairing":
        return (
            lambda d: (d.hero_position, d.villain_position),
            lambda k: f"Hero {k[0]} vs {k[1]}",
            lambda k: (_pos_key(k[0]), _pos_key(k[1])),
        )
    if kind == "bucket":
        names = [b for b, _ in SIZE_BUCKETS]
        return lambda d: d.size_bucket, lambda k: f"Open size {k}", lambda k: names.index(k)
    if kind == "pairing+bucket":
        names = [b for b, _ in SIZE_BUCKETS]
        return (
            lambda d: (d.hero_position, d.villain_position, d.size_bucket),
            lambda k: f"Hero {k[0]} vs {k[1]}, open size {k[2]}",
            lambda k: (_pos_key(k[0]), _pos_key(k[1]), names.index(k[2])),
        )
    if kind == "in_position":
        return (
            lambda d: d.in_position,
            lambda k: "Hero in position" if k else "Hero out of position",
            lambda k: not k,
        )
    raise ValueError(kind)


def pairing_table(decisions: list[Decision], situation: str) -> str:
    has_villain = any(d.villain_position for d in decisions)
    key = (lambda d: (d.hero_position, d.villain_position)) if has_villain else (lambda d: (d.hero_position, None))
    stats = _by(decisions, key)
    call = CALL_LABEL.get(situation, "Call")
    rows = []
    for (hero, villain), s in sorted(stats.items(), key=lambda kv: (_pos_key(kv[0][0]), _pos_key(kv[0][1]))):
        sizes = [d.faced_bb for d in decisions if key(d) == (hero, villain) and d.faced_bb]
        rows.append(
            f"<tr><th>{_e(hero)}</th>" + (f"<th>{_e(villain)}</th>" if has_villain else "") + f"<td>{s.n}</td>"
            + "".join(f"<td>{_pct(s.count[a], s.n)}</td>" for a in ACTIONS)
            + (f"<td>{statistics.median(sizes):.2f}</td>" if has_villain and sizes else ("<td></td>" if has_villain else ""))
            + f"<td>{_bb(s.total, s.n)}</td></tr>"
        )
    villain_head = "<th>Villain</th>" if has_villain else ""
    size_head = "<th>Median raise faced (bb)</th>" if has_villain else ""
    return (
        f'<div class="table-wrap"><table><thead><tr><th>Hero</th>{villain_head}<th>Times</th><th>Raise</th>'
        f"<th>{call}</th><th>Fold</th>{size_head}<th>Avg bb, all</th></tr></thead>"
        f'<tbody>{"".join(rows)}</tbody></table></div>'
    )


def situation_section(situation: str, decisions: list[Decision]) -> str:
    title = SITUATIONS[situation]
    out = [f'<section id="{situation}"><h2>{_e(title)} <span class="count">{len(decisions)} decisions</span></h2>']
    if situation == "other":
        kinds = Counter(d.other_kind for d in decisions)
        rows = "".join(f"<tr><th>{_e(k)}</th><td>{n}</td></tr>" for k, n in kinds.most_common())
        out.append(
            '<p>Spots that fit none of the situations above. They are counted here and not charted.</p>'
            f'<div class="table-wrap"><table><thead><tr><th>Spot</th><th>Decisions</th></tr></thead>'
            f"<tbody>{rows}</tbody></table></div></section>"
        )
        return "".join(out)
    out.append(grid_html(decisions, situation))
    out.append("<h3>By position</h3>" + pairing_table(decisions, situation))
    for kind in SPLITS.get(situation, []):
        key, label, order = _split_key(kind)
        groups = defaultdict(list)
        for d in decisions:
            if (k := key(d)) is not None and (not isinstance(k, tuple) or None not in k):
                groups[k].append(d)
        shown = [(k, ds) for k, ds in groups.items() if len(ds) >= MIN_GRID]
        if not shown or (len(shown) == 1 and len(shown[0][1]) == len(decisions)):
            continue
        skipped = len(groups) - len(shown)
        heading = {"position": "Grids by Hero position", "pairing": "Grids by Hero position vs villain position",
                   "bucket": "Grids by open size faced", "pairing+bucket": "Grids by position pairing and open size",
                   "in_position": "Grids by Hero in or out of position"}[kind]
        note = f' <span class="count">{skipped} smaller splits not charted</span>' if skipped else ""
        out.append(f"<h3>{heading}{note}</h3>")
        for k, ds in sorted(shown, key=lambda kv: order(kv[0])):
            out.append(
                f"<details><summary>{_e(label(k))} <span class='count'>{len(ds)} decisions</span></summary>"
                f"{grid_html(ds, situation)}</details>"
            )
    out.append("</section>")
    return "".join(out)


def _size_summary(sizes: list[float]) -> str:
    common = Counter(round(s, 2) for s in sizes).most_common(4)
    def share(n: int) -> str:
        pct = 100 * n / len(sizes)
        return f"{pct:.0f}%" if pct >= 0.5 else "<1%"

    return " · ".join(f"{s:g}bb {share(n)}" for s, n in common)


def sizing_section(decisions: list[Decision]) -> str:
    def table(head: list[str], rows: list[list[str]]) -> str:
        if not rows:
            return '<p class="muted">No hands.</p>'
        return (
            '<div class="table-wrap"><table><thead><tr>' + "".join(f"<th>{h}</th>" for h in head) + "</tr></thead><tbody>"
            + "".join("<tr>" + "".join(rows_) + "</tr>" for rows_ in rows) + "</tbody></table></div>"
        )

    def size_row(label: str, sizes: list[float], extra: list[str] = ()) -> list[str]:
        return [f"<th>{_e(label)}</th>", f"<td>{len(sizes)}</td>", f"<td>{statistics.median(sizes):.2f}</td>",
                f"<td>{statistics.mean(sizes):.2f}</td>", *extra, f"<td class='left'>{_size_summary(sizes)}</td>"]

    raises = [d for d in decisions if d.action == "raise" and not d.hero_all_in]
    shoves = sum(1 for d in decisions if d.action == "raise" and d.hero_all_in)
    out = ['<section id="sizing"><h2>Hero\'s sizing</h2>',
           f"<p>Raise sizes are Hero's total bet in big blinds. All-in raises ({shoves}) are left out.</p>"]

    opens = defaultdict(list)
    for d in raises:
        if d.situation in ("rfi", "bvb"):
            opens[d.hero_position].append(d.raise_to_bb)
    out.append("<h3>Open sizes by position</h3>")
    out.append(table(["Position", "Opens", "Median", "Mean", "Most common sizes"],
                     [size_row(p, opens[p]) for p in sorted(opens, key=_pos_key)]))

    threebets = defaultdict(list)
    for d in raises:
        if d.situation in ("vs_open", "squeeze"):
            where = "In position" if d.in_position else "Out of position"
            spot = "vs an open" if d.situation == "vs_open" else "squeeze"
            threebets[(where, spot)].append(d)
    rows = []
    for (where, spot), ds in sorted(threebets.items()):
        multiples = [d.raise_to_bb / d.faced_bb for d in ds]
        rows.append(size_row(f"{where}, {spot}", [d.raise_to_bb for d in ds],
                             [f"<td>{statistics.median(multiples):.2f}×</td>"]))
    out.append("<h3>3-bet sizes in and out of position</h3>")
    out.append("<p>In position means Hero acts after the opener after the flop. The blinds are always out of position.</p>")
    out.append(table(["Spot", "3-bets", "Median", "Mean", "Median × open", "Most common sizes"], rows))

    iso = defaultdict(list)
    for d in raises:
        if d.situation == "vs_limpers":
            iso[f"{min(d.limpers, 3)}{'+' if d.limpers >= 3 else ''} limper{'s' if d.limpers > 1 else ''}"].append(d.raise_to_bb)
        elif d.situation == "bb_vs_sb_limp":
            iso["BB vs SB limp"].append(d.raise_to_bb)
    out.append("<h3>Raise sizes vs limpers</h3>")
    out.append(table(["Spot", "Raises", "Median", "Mean", "Most common sizes"], [size_row(k, v) for k, v in sorted(iso.items())]))
    out.append("</section>")
    return "".join(out)


def overview_section(ds: DecisionSet, meta: dict) -> str:
    by_situation = Counter(d.situation for d in ds.decisions)
    rows = "".join(
        f'<tr><th><a href="#{s}">{_e(SITUATIONS[s])}</a></th><td>{by_situation[s]}</td></tr>' for s in SITUATIONS
    )
    excluded = "".join(f"<tr><th>{_e(r)}</th><td>{n}</td></tr>" for r, n in ds.excluded.most_common())
    total = sum(ds.opponent_open_sizes.values())
    sizes = sorted(ds.opponent_open_sizes.items())
    common = [(s, n) for s, n in sizes if n / total >= 0.005]
    rare = total - sum(n for _, n in common)
    open_rows = "".join(
        f"<tr><th>{s:g}bb</th><td>{n}</td><td>{100 * n / total:.1f}%</td>"
        f'<td class="left"><span class="bar" style="width:{300 * n / total:.1f}px"></span></td></tr>'
        for s, n in common
    ) + f"<tr><th>other sizes</th><td>{rare}</td><td>{100 * rare / total:.1f}%</td><td></td></tr>"
    bucket_counts = Counter(d.size_bucket for d in ds.decisions if d.situation == "vs_open")
    buckets = "".join(f"<li><b>{_e(b)}</b>: {bucket_counts[b]} of Hero's facing-an-open decisions</li>" for b, _ in SIZE_BUCKETS)
    return f"""
<section id="overview">
<h2>Overview</h2>
<p>{ds.hands_seen:,} hands from {meta['sessions']} sessions, {meta['first']} to {meta['last']} ({_e(meta['time_zone'])}),
stakes {_e(meta['stakes'])}. All amounts are in big blinds of the hand they came from.</p>
<div class="cols">
<div><h3>Hero decisions by situation</h3><div class="table-wrap"><table><thead><tr><th>Situation</th><th>Decisions</th></tr></thead>
<tbody>{rows}<tr class="total"><th>All</th><td>{len(ds.decisions)}</td></tr></tbody></table></div></div>
<div><h3>Hands left out</h3><div class="table-wrap"><table><thead><tr><th>Reason</th><th>Hands</th></tr></thead>
<tbody>{excluded or '<tr><td colspan="2">None</td></tr>'}<tr class="total"><th>All</th><td>{sum(ds.excluded.values())}</td></tr></tbody></table></div></div>
</div>
<h3>How results are counted</h3>
<p>The result of a decision is what Hero gets back from the pot minus only the money Hero puts in from that decision on.
Blinds and earlier bets are already gone, so a fold is always 0. A call that loses shows just the amount called (plus any later bets).</p>
<p>In {ds.all_in_hands} hands Hero was all-in with cards shown before the river. There, Hero's share of the pot is Hero's exact
equity times the pot after rake and fees, instead of what actually happened; this also replaces run-it-twice and EV Cashout outcomes.
Side pots are valued separately with the equity among the players in each.{f" {ds.all_in_unshown} all-in hands had unshown cards and keep their actual results." if ds.all_in_unshown else ""}
Equity is exact: every remaining board is enumerated with a vectorised 7-card evaluator, checked against the phevaluator library.</p>
<h3>Open sizes faced</h3>
<p>Every first raise by an opponent with no limpers before it, in hands without a straddle ({total:,} opens). The buckets follow the clusters:</p>
<ul>{buckets}</ul>
<div class="table-wrap"><table class="sizes"><thead><tr><th>Open to</th><th>Opens</th><th>Share</th><th></th></tr></thead><tbody>{open_rows}</tbody></table></div>
</section>"""


STYLE = """
:root{--bg:#fafaf8;--panel:#fff;--text:#1d1f23;--muted:#6b7078;--line:#e3e3df;--raise:#d0473f;--call:#3a9a5b;
--fold:#4b6fa8;--empty:#ecece8;--pos:#25844a;--neg:#c0392b;--accent:#2f5d9e}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#15171a;--panel:#1d2024;--text:#e7e7e4;--muted:#9aa0a8;
--line:#2f3338;--empty:#2a2d31;--pos:#5cc283;--neg:#ef7a6c;--accent:#8fb4ec;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#15171a;--panel:#1d2024;--text:#e7e7e4;--muted:#9aa0a8;--line:#2f3338;--empty:#2a2d31;
--pos:#5cc283;--neg:#ef7a6c;--accent:#8fb4ec;color-scheme:dark}
body{background:var(--bg);color:var(--text);font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;margin:0}
main{max-width:1100px;margin:0 auto;padding-block:24px 64px;padding-inline:16px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:20px;margin:40px 0 12px;padding-top:12px;border-top:1px solid var(--line)}
h3{font-size:15px;margin:20px 0 8px}a{color:var(--accent)}.muted,.count{color:var(--muted);font-weight:400;font-size:13px}
nav{display:flex;flex-wrap:wrap;gap:6px 14px;margin:12px 0 4px;font-size:13px}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:13px;margin:8px 0}
.legend span::before{content:"";display:inline-block;width:12px;height:12px;border-radius:2px;margin-right:5px;vertical-align:-1px;background:var(--c)}
.grid-wrap{overflow-x:auto;margin:8px 0 12px}
.grid{display:grid;grid-template-columns:repeat(13,minmax(40px,1fr));gap:2px;min-width:560px;max-width:780px}
.cell{aspect-ratio:1;border-radius:3px;color:#fff;text-shadow:0 0 3px rgba(0,0,0,.55);display:flex;flex-direction:column;
align-items:center;justify-content:center;font-size:12px;line-height:1.15;cursor:default}
.cell b{font-weight:600}.cell i{font-style:normal;font-size:10px;opacity:.9}
.cell.empty{background:var(--empty);color:var(--muted);text-shadow:none}.cell.faint{opacity:.5}
.table-wrap{overflow-x:auto}table{border-collapse:collapse;font-size:13px;margin:4px 0 8px;background:var(--panel)}
th,td{padding:4px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th{font-weight:500}tbody th{text-align:left}thead th{color:var(--muted);font-weight:500;text-align:right}
thead th:first-child{text-align:left}td.left{text-align:left}tr.total th,tr.total td{font-weight:600}
.pos{color:var(--pos)}.neg{color:var(--neg)}
details{margin:6px 0;border:1px solid var(--line);border-radius:6px;padding:6px 10px;background:var(--panel)}
summary{cursor:pointer;font-weight:500}
.cols{display:flex;flex-wrap:wrap;gap:8px 40px}.bar{display:inline-block;height:10px;background:var(--accent);border-radius:2px;max-width:100%}
"""


def build_html(ds: DecisionSet, meta: dict) -> str:
    by_situation = defaultdict(list)
    for d in ds.decisions:
        by_situation[d.situation].append(d)
    nav = "".join(f'<a href="#{s}">{_e(SITUATIONS[s])}</a>' for s in SITUATIONS if by_situation[s])
    sections = "".join(situation_section(s, by_situation[s]) for s in SITUATIONS if by_situation[s])
    legend = (
        '<div class="legend"><span style="--c:var(--raise)">Raise</span><span style="--c:var(--call)">'
        'Call / limp / check</span><span style="--c:var(--fold)">Fold</span>'
        '<span class="muted">Each square shows the hand and how many times it came up; hover for details. '
        "Faded squares came up once or twice.</span></div>"
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Preflop report</title><style>{STYLE}</style></head>
<body><main><h1>Preflop report</h1><p class="muted">Generated {meta['generated']} from {_e(meta['db'])}.
Splits with fewer than {MIN_GRID} decisions get no grid of their own.</p>
<nav><a href="#overview">Overview</a>{nav}<a href="#sizing">Hero's sizing</a></nav>
{overview_section(ds, meta)}{legend}{sections}{sizing_section(ds.decisions)}</main></body></html>
"""


def report_meta(conn, db_path: Path) -> dict:
    first, last = conn.execute("SELECT MIN(played_at), MAX(played_at) FROM hands").fetchone()
    stakes = conn.execute(
        "SELECT DISTINCT small_blind_cents, big_blind_cents FROM hands ORDER BY big_blind_cents"
    ).fetchall()
    zones = {r[0] for r in conn.execute("SELECT DISTINCT time_zone FROM hands")}
    return {
        "sessions": conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
        "first": first, "last": last, "time_zone": ", ".join(sorted(zones)),
        "stakes": ", ".join(f"${sb / 100:g}/${bb / 100:g}" for sb, bb in stakes),
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "db": db_path.name,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Write the preflop report.")
    ap.add_argument("--db", default=settings.DB_PATH, type=Path)
    ap.add_argument("--out", default=REPORT_PATH, type=Path)
    args = ap.parse_args(argv)
    conn = db.connect(args.db)
    try:
        ds = hero_decisions(conn, settings.DATA_DIR / "equity_cache.json")
        meta = report_meta(conn, args.db)
    finally:
        conn.close()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build_html(ds, meta), encoding="utf-8")
    print(f"{len(ds.decisions)} Hero decisions from {ds.hands_seen} hands; {sum(ds.excluded.values())} hands left out.")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
