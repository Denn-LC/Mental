"""Saved players, rounds and attempts, in one SQLite file.

Every statement is a fixed string with ? placeholders, and the values are passed separately, so
nothing a player types can change what a query does. Never build SQL with f-strings, %, .format or +.
"""
import hashlib
import json
import os
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Schema version 2. Statements run in order inside one transaction; the last sets the version.
# A round is one finished test or practice session. Players come from Google sign-in and have no
# display name until they choose one. Sessions store only a hash of their token.
SCHEMA = [
    """CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY,
        google_sub TEXT NOT NULL UNIQUE,
        name TEXT UNIQUE COLLATE NOCASE,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY,
        player_id INTEGER NOT NULL REFERENCES players(id),
        expires_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS oauth_states (
        state TEXT PRIMARY KEY,
        code_verifier TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS rounds (
        id INTEGER PRIMARY KEY,
        player_id INTEGER NOT NULL REFERENCES players(id),
        mode TEXT NOT NULL CHECK (mode IN ('practice', 'test')),
        score INTEGER NOT NULL,
        finished_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS attempts (
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
        wrong_tries TEXT NOT NULL,
        time_ms INTEGER NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS rounds_by_player ON rounds (player_id, mode)",
    "CREATE INDEX IF NOT EXISTS attempts_by_round ON attempts (round_id)",
    "CREATE INDEX IF NOT EXISTS sessions_by_player ON sessions (player_id)",
    "PRAGMA user_version = 2",
]
SCHEMA_VERSION = 2  # must match the PRAGMA user_version that ends SCHEMA
# v1.2's name-only players are deleted on upgrade (after a backup), as the v1.3 spec says.
DROP_V1 = ["DROP TABLE IF EXISTS attempts", "DROP TABLE IF EXISTS rounds", "DROP TABLE IF EXISTS players"]
SESSION_DAYS = 30
STATE_MINUTES = 10


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
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            upgrade(conn, path)
    except BaseException:
        conn.close()
        raise
    return conn


def backup_v1(conn, path):
    """Write a complete copy of a version 1 file next to it, under a name no earlier backup has."""
    temp = path.with_name(f"{path.name}.v1-backup.tmp-{secrets.token_hex(4)}")
    try:
        target = sqlite3.connect(temp)
        try:
            conn.backup(target)
        finally:
            target.close()
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        names = [f"{path.name}.v1-backup", f"{path.name}.v1-backup-{stamp}"]
        names += [f"{path.name}.v1-backup-{stamp}-{n}" for n in range(2, 1000)]
        for name in names:
            final = path.with_name(name)
            try:
                os.link(temp, final)  # fails if the name is taken, so a backup is never overwritten
            except FileExistsError:
                continue
            return final
        raise RuntimeError("no free name for the v1 backup")
    finally:
        temp.unlink(missing_ok=True)


def upgrade(conn, path):
    """Bring the file to SCHEMA_VERSION. A version 1 file is backed up first (always a new, complete
    backup, never replacing an older one), then cleared."""
    if conn.execute("PRAGMA user_version").fetchone()[0] == 1:
        backup_v1(conn, path)
    conn.execute("BEGIN IMMEDIATE")  # one connection upgrades at a time
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]  # another may have done it meanwhile
        if version > SCHEMA_VERSION:
            raise RuntimeError(f"{path} was made by a newer version of mental (schema {version})")
        if version == 1:
            for statement in DROP_V1:
                conn.execute(statement)
        if version < SCHEMA_VERSION:
            for statement in SCHEMA:
                conn.execute(statement)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def now():
    return datetime.now(UTC).isoformat(timespec="seconds")


def later(**delta):
    return (datetime.now(UTC) + timedelta(**delta)).isoformat(timespec="seconds")


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def player_for_google(conn, sub):
    """The player for this Google account, made on its first sign-in (with no display name yet)."""
    with conn:
        conn.execute(
            "INSERT INTO players (google_sub, created_at) VALUES (?, ?) ON CONFLICT(google_sub) DO NOTHING",
            (sub, now()),
        )
    return dict(conn.execute("SELECT id, name FROM players WHERE google_sub = ?", (sub,)).fetchone())


def set_name(conn, player_id, name):
    try:
        with conn:
            conn.execute("UPDATE players SET name = ? WHERE id = ?", (name, player_id))
    except sqlite3.IntegrityError:
        raise NameTaken(name) from None


def create_session(conn, player_id):
    """A new random session token for the player. Only its hash is stored."""
    token = secrets.token_urlsafe(32)
    with conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now(),))
        conn.execute(
            "INSERT INTO sessions (token_hash, player_id, expires_at) VALUES (?, ?, ?)",
            (token_hash(token), player_id, later(days=SESSION_DAYS)),
        )
    return token


def session_player(conn, token):
    """The player ({id, name}) a session token belongs to, or None if it's unknown or expired."""
    if not token:
        return None
    row = conn.execute(
        """SELECT p.id, p.name FROM sessions s JOIN players p ON p.id = s.player_id
           WHERE s.token_hash = ? AND s.expires_at > ?""",
        (token_hash(token), now()),
    ).fetchone()
    return dict(row) if row else None


def end_session(conn, token):
    if not token:
        return
    with conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))


def save_oauth_state(conn, state, code_verifier):
    with conn:
        conn.execute("DELETE FROM oauth_states WHERE expires_at < ?", (now(),))
        conn.execute(
            "INSERT INTO oauth_states (state, code_verifier, expires_at) VALUES (?, ?, ?)",
            (state, code_verifier, later(minutes=STATE_MINUTES)),
        )


def take_oauth_state(conn, state):
    """The code_verifier saved for this state, or None. A state works once: it is deleted here."""
    with conn:
        row = conn.execute(
            "DELETE FROM oauth_states WHERE state = ? RETURNING code_verifier, expires_at", (state,)
        ).fetchone()
    if row is None or row["expires_at"] <= now():
        return None
    return row["code_verifier"]


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
    """Top 10 named players by best test score (ties alphabetical). Players with no test are left out."""
    rows = conn.execute(
        """SELECT p.id, p.name, MAX(r.score) AS best FROM rounds r JOIN players p ON p.id = r.player_id
           WHERE r.mode = 'test' AND p.name IS NOT NULL
           GROUP BY p.id ORDER BY best DESC, p.name COLLATE NOCASE LIMIT 10"""
    )
    return [dict(row) for row in rows]
