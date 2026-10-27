"""Project-wide settings."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "poker.db"
IMPORT_REPORT_PATH = DATA_DIR / "import_report.txt"

# Time zone of the timestamps in GGPoker hand history headers. The header itself names no zone.
# In every file so far the time in the file name (GG20260902-0500) is exactly 4 hours ahead of the
# first hand's header time, which fits file names in UTC and headers in US Eastern daylight time.
# Hands from after the DST change (2026-11-01) will confirm it: the gap should become 5 hours.
# Timestamps are stored exactly as written; this name is stored alongside them.
HAND_HISTORY_TIMEZONE = "America/New_York"
