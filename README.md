# Poker Analyzer

Analyzes GGPoker hand histories to find leaks.

## Setup (Windows)

Activate the virtual environment in PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks the script, allow local scripts once for your user:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

In Command Prompt, use `.venv\Scripts\activate.bat` instead.

Install dependencies:

```powershell
pip install -r requirements.txt
```

## Running tests

With the venv active:

```powershell
python -m pytest
```

Or without activating:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Deactivate the venv with `deactivate`.

## Parsing hand histories

Put GGPoker `.txt` hand histories in `data/raw/`, then with the venv active:

```powershell
python -m poker_analyzer.parser
```

It reports how many hands parsed, any that failed, any lines it didn't recognize,
and any hands whose chip totals don't add up. You can also pass specific files or folders.

## Importing into the database

```powershell
python -m poker_analyzer.importer
```

Imports every `.txt` file in `data/raw/` into `data/poker.db` (SQLite) and writes the full
report to `data/import_report.txt`. It's safe to re-run: imported files are skipped and no
hand is stored twice. Hands it can't read are listed with the reason and retried next run.

Hand timestamps are stored exactly as written. Their time zone is the single
`HAND_HISTORY_TIMEZONE` setting in `src/poker_analyzer/settings.py`.
