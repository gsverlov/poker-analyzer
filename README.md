# Poker Analyzer

Analyzes GGPoker hand histories to find leaks in preflop and postflop play.
Imports hands into a local SQLite database, scores every preflop decision
against a solver chart, and (in later parts) flags postflop mistakes using
statistical and ML-based methods.

## Setup

Requires Python 3.10 or later.

Create and activate a virtual environment, then install in editable mode:

```bash
python -m venv .venv
```

Activate (Windows PowerShell):

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks the script, allow local scripts once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Activate (Windows Command Prompt):

```bat
.venv\Scripts\activate.bat
```

Install dependencies:

```bash
pip install -e .
pip install -r requirements.txt
```

The report layout test opens an HTML report in a headless browser. Install
Chromium once if you want that test to run:

```bash
python -m playwright install chromium
```

Without it the layout test is skipped automatically.

## Importing hand histories

Put GGPoker `.txt` hand history files in `data/raw/`, then run:

```bash
python -m poker_analyzer.importer
```

Imports every file in `data/raw/` into `data/poker.db` (SQLite) and writes a
full import log to `data/import_report.txt`. Re-running is safe: already-imported
files are skipped and no hand is stored twice. Hands it cannot read are listed
with the reason and retried next run.

Hand timestamps are stored exactly as written. The time zone is set via
`HAND_HISTORY_TIMEZONE` in `src/poker_analyzer/settings.py`.

You can also run the parser standalone to check a file without importing:

```bash
python -m poker_analyzer.parser path/to/file.txt
```

## Running reports

### Preflop report

```bash
python -m poker_analyzer.preflop_report
```

Reads `data/poker.db` and writes `reports/preflop.html`. All-in equities are
cached in `data/equity_cache.json` so only the first run is slow.

### Preflop vs chart

```bash
python -m poker_analyzer.chart_report
```

Compares preflop decisions against the solver chart and writes
`reports/preflop_vs_chart.html` with top leaks, strengths, and
side-by-side frequency grids for every spot.

Requires `charts/pokalab_6max.json` — see note below.

## Running tests

```bash
python -m pytest
```

## Status

### Built

- Hand history import (parser + bulk importer + SQLite schema)
- Preflop decision report (open sizing, 3-bet frequency, fold-to-3bet, etc.)
- Chart comparison (preflop decisions vs Pokalab 6-max solver output)

### Placeholder (not yet implemented)

- **Postflop report (Part 3)** — board texture classification, hand-strength
  bucketing, river call accuracy, missed value bets, c-bet and fold
  frequencies (`src/poker_analyzer/board_texture.py`,
  `hand_strength.py`, `postflop_labels.py`, `postflop_report.py`)
- **ML opponent model (Part 4)** — feature extraction, logistic regression
  baseline, LightGBM multiclass classifier, bluff EV scorer
  (`src/poker_analyzer/ml/`)
- **Final leak report (Part 5)** — ranked leak list with bootstrap confidence
  intervals and holdout confirmation
  (`src/poker_analyzer/leak_report.py`, `stats.py`, `holdout.py`)
- **Tilt and fatigue detection (Part 5)** — compares play quality before and
  after downswings or long sessions (`src/poker_analyzer/tilt.py`)

All placeholder modules import cleanly and are covered by smoke tests in
`tests/test_placeholders.py`, keeping the test suite green until each part
is built.

## Solver chart data

`charts/pokalab_6max.json` is **not included** in this repository (proprietary
solver data). To enable chart comparison, place the file at
`charts/pokalab_6max.json`. The path is listed in `.gitignore` and will never
be committed.

## Planned dependencies

The ML modules (Part 4) will require packages not yet in `requirements.txt`:

- `scikit-learn >= 1.4`
- `lightgbm >= 4.0`
