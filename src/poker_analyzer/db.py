"""SQLite schema and connection for the hand database.

Only raw facts from the hand histories are stored, with all money as integer
cents. Anything derived from many hands (VPIP and other stats) belongs in
queries, not columns.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id                INTEGER PRIMARY KEY,
    file_name         TEXT NOT NULL UNIQUE,
    file_sha256       TEXT NOT NULL,
    table_name        TEXT NOT NULL,
    currency          TEXT NOT NULL,
    small_blind_cents INTEGER NOT NULL,
    big_blind_cents   INTEGER NOT NULL,
    max_seats         INTEGER NOT NULL,
    complete          INTEGER NOT NULL DEFAULT 0  -- 1 once every hand in the file is imported
);

CREATE TABLE IF NOT EXISTS hands (
    hand_id           TEXT PRIMARY KEY,
    session_id        INTEGER NOT NULL REFERENCES sessions(id),
    session_order     INTEGER NOT NULL,  -- 1 = oldest hand in the file
    played_at         TEXT NOT NULL,     -- exactly as written in the header, e.g. 2026/09/02 02:24:51
    time_zone         TEXT NOT NULL,     -- IANA name the header time is in
    game              TEXT NOT NULL,
    small_blind_cents INTEGER NOT NULL,
    big_blind_cents   INTEGER NOT NULL,
    button_seat       INTEGER NOT NULL,
    board             TEXT,              -- space-separated cards; the first board when run more than once
    run_count         INTEGER NOT NULL DEFAULT 1,
    board_run2        TEXT,              -- full five-card boards of later runs
    board_run3        TEXT,
    total_pot_cents   INTEGER NOT NULL,
    rake_cents        INTEGER NOT NULL,
    jackpot_cents     INTEGER NOT NULL,
    bingo_cents       INTEGER NOT NULL,
    fortune_cents     INTEGER NOT NULL,
    tax_cents         INTEGER NOT NULL,
    raw_text          TEXT NOT NULL,
    parser_version    INTEGER NOT NULL,
    UNIQUE (session_id, session_order)
);

CREATE TABLE IF NOT EXISTS players (
    id         INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    hh_id      TEXT NOT NULL,  -- the ID shown in the hand history ("Hero" for you)
    is_hero    INTEGER NOT NULL DEFAULT 0,
    UNIQUE (session_id, hh_id)
);

CREATE TABLE IF NOT EXISTS seats (
    hand_id                TEXT NOT NULL REFERENCES hands(hand_id),
    player_id              INTEGER NOT NULL REFERENCES players(id),
    seat_no                INTEGER NOT NULL,
    position               TEXT,              -- UTG HJ CO BTN SB BB, or BTN/SB heads-up; NULL if not dealt in
    stack_cents            INTEGER NOT NULL,  -- starting stack
    dealt_in               INTEGER NOT NULL,
    hole_cards             TEXT,              -- Hero's cards, or cards shown at showdown; NULL if unknown
    showed                 INTEGER NOT NULL,  -- 1 if the cards were shown to the table
    invested_cents         INTEGER NOT NULL,  -- chips put in the pot, after uncalled bets came back
    collected_cents        INTEGER NOT NULL,  -- chips taken from the pot, all pots and runs
    net_cents              INTEGER NOT NULL,  -- collected - invested
    time_bank_cents        INTEGER NOT NULL DEFAULT 0,  -- time bank card received (+) or bought (-), outside the pot
    cashout_chosen         INTEGER NOT NULL DEFAULT 0,  -- took GGPoker's all-in EV Cashout
    cashout_received_cents INTEGER,           -- paid outside the pot after cashing out
    cashout_risk_cents     INTEGER,           -- given up after cashing out and winning
    PRIMARY KEY (hand_id, seat_no),
    UNIQUE (hand_id, player_id)
);

CREATE TABLE IF NOT EXISTS actions (
    hand_id          TEXT NOT NULL REFERENCES hands(hand_id),
    seq              INTEGER NOT NULL,  -- 1-based order within the hand
    street           TEXT NOT NULL CHECK (street IN ('preflop', 'flop', 'turn', 'river')),
    player_id        INTEGER NOT NULL REFERENCES players(id),
    action           TEXT NOT NULL CHECK (action IN (
                         'post_sb', 'post_bb', 'post_dead', 'straddle',
                         'fold', 'check', 'call', 'bet', 'raise')),
    amount_cents     INTEGER,           -- as written; for raises the increment, for straddles the total
    raise_to_cents   INTEGER,           -- raises and straddles: total bet on this street
    is_all_in        INTEGER NOT NULL,
    pot_before_cents INTEGER NOT NULL,  -- everything in the pot just before this action
    PRIMARY KEY (hand_id, seq)
);

CREATE INDEX IF NOT EXISTS hands_session ON hands(session_id);
CREATE INDEX IF NOT EXISTS seats_player ON seats(player_id);
CREATE INDEX IF NOT EXISTS actions_player ON actions(player_id);
"""

TABLES = ("sessions", "hands", "players", "seats", "actions")


def connect(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the database. Transactions are explicit: callers BEGIN and COMMIT."""
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise RuntimeError(f"{path} has schema version {version}; this code knows up to {SCHEMA_VERSION}")
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return conn


def row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
