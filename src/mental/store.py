"""Saved players, rounds and attempts, in one SQLite file.

Every statement is a fixed string with ? placeholders, and the values are passed separately, so
nothing a player types can change what a query does. Never build SQL with f-strings, %, .format or +.
"""
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

# A round is one finished test or practice session. PRAGMA user_version is the schema version,
# so a later version can see what it is upgrading from.
SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rounds (
    id INTEGER PRIMARY KEY,
    player_id INTEGER NOT NULL REFERENCES players(id),
    mode TEXT NOT NULL CHECK (mode IN ('practice', 'test')),
    score INTEGER NOT NULL,
    finished_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY,
    round_id INTEGER NOT NULL REFERENCES rounds(id),
    question_id TEXT NOT NULL,
    seed INTEGER NOT NULL,
    text TEXT NOT NULL,
    category TEXT NOT NULL,
    strategy TEXT NOT NULL,
    difficulty INTEGER NOT NULL,
    answer INTEGER NOT NULL,
    given TEXT NOT NULL,
    correct INTEGER NOT NULL,
    skipped INTEGER NOT NULL,
    gave_up INTEGER NOT NULL,
    wrong_tries TEXT NOT NULL,  -- JSON list of strings
    time_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS rounds_by_player ON rounds (player_id, mode);
CREATE INDEX IF NOT EXISTS attempts_by_round ON attempts (round_id);
PRAGMA user_version = 1;
"""


class NameTaken(Exception):
    pass


def db_path():
    return Path(os.environ.get("MENTAL_DB") or Path.home() / ".mental" / "mental.db")


def connect(path=None):
    path = Path(path or db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    # FastAPI may open the connection on one worker thread and use it on another (never at once)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if conn.execute("PRAGMA user_version").fetchone()[0] == 0:
        conn.executescript(SCHEMA)
    return conn


def now():
    return datetime.now(UTC).isoformat(timespec="seconds")


def add_player(conn, name):
    try:
        with conn:
            cursor = conn.execute("INSERT INTO players (name, created_at) VALUES (?, ?)", (name, now()))
    except sqlite3.IntegrityError:
        raise NameTaken(name) from None
    return {"id": cursor.lastrowid, "name": name}


def players(conn):
    return [dict(row) for row in conn.execute("SELECT id, name FROM players ORDER BY name COLLATE NOCASE")]


def player_exists(conn, player_id):
    return conn.execute("SELECT 1 FROM players WHERE id = ?", (player_id,)).fetchone() is not None


def save_round(conn, player_id, mode, attempts):
    """Store a finished round and its attempts (already checked). Returns the round id."""
    score = sum(1 for a in attempts if a["correct"])
    with conn:
        cursor = conn.execute(
            "INSERT INTO rounds (player_id, mode, score, finished_at) VALUES (?, ?, ?, ?)",
            (player_id, mode, score, now()),
        )
        conn.executemany(
            """INSERT INTO attempts (round_id, question_id, seed, text, category, strategy, difficulty,
                   answer, given, correct, skipped, gave_up, wrong_tries, time_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (cursor.lastrowid, a["question_id"], a["seed"], a["text"], a["category"], a["strategy"],
                 a["difficulty"], a["answer"], a["given"], a["correct"], a["skipped"], a["gave_up"],
                 json.dumps(a["wrong_tries"]), a["time_ms"])
                for a in attempts
            ],
        )
    return cursor.lastrowid


def best_score(conn, player_id):
    """Best test score, or None before the first test."""
    return conn.execute(
        "SELECT MAX(score) FROM rounds WHERE player_id = ? AND mode = 'test'", (player_id,)
    ).fetchone()[0]


def history(conn, player_id):
    """How many tests, the best score and the last 10 scores, newest first."""
    count, best = conn.execute(
        "SELECT COUNT(*), MAX(score) FROM rounds WHERE player_id = ? AND mode = 'test'", (player_id,)
    ).fetchone()
    recent = conn.execute(
        "SELECT score, finished_at AS at FROM rounds WHERE player_id = ? AND mode = 'test' ORDER BY id DESC LIMIT 10",
        (player_id,),
    )
    return {"count": count, "best": best, "recent": [dict(row) for row in recent]}


def player_attempts(conn, player_id):
    """Every saved attempt of one player, shaped like the records summary.py reads."""
    rows = conn.execute(
        """SELECT a.*, r.mode FROM attempts a JOIN rounds r ON r.id = a.round_id
           WHERE r.player_id = ? ORDER BY a.id""",
        (player_id,),
    )
    return [
        {**dict(row), "correct": bool(row["correct"]), "skipped": bool(row["skipped"]),
         "gave_up": bool(row["gave_up"]), "wrong_tries": json.loads(row["wrong_tries"])}
        for row in rows
    ]


def leaderboard(conn):
    """Top 10 players by best test score (ties alphabetical). Players with no test are left out."""
    rows = conn.execute(
        """SELECT p.id, p.name, MAX(r.score) AS best FROM rounds r JOIN players p ON p.id = r.player_id
           WHERE r.mode = 'test' GROUP BY p.id ORDER BY best DESC, p.name COLLATE NOCASE LIMIT 10"""
    )
    return [dict(row) for row in rows]
