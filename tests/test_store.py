import hashlib
import sqlite3
from pathlib import Path

import pytest

from mental import store
from mental.engine.check import checked
from records import records

LONG_AGO = "2000-01-01T00:00:00+00:00"


@pytest.fixture
def conn(tmp_path):
    conn = store.connect(tmp_path / "test.db")
    yield conn
    conn.close()


def saved(right, wrong=0):
    """Checked records, as the API hands them to the store."""
    return [checked(a) for a in records(right, wrong)]


def named(conn, name, sub=None):
    """A signed-in player with a display name; returns its id."""
    player = store.player_for_google(conn, sub or f"google-{name}")
    store.set_name(conn, player["id"], name)
    return player["id"]


def test_new_database_has_schema_version_2(conn):
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2 == store.SCHEMA_VERSION


def test_a_google_account_gets_one_player(conn):
    first = store.player_for_google(conn, "google-1")
    assert first["name"] is None
    store.set_name(conn, first["id"], "me")
    assert store.player_for_google(conn, "google-1") == {"id": first["id"], "name": "me"}
    assert store.player_for_google(conn, "google-2")["id"] != first["id"]


def test_names_are_unique_ignoring_case(conn):
    named(conn, "Denn")
    other = store.player_for_google(conn, "google-other")
    with pytest.raises(store.NameTaken):
        store.set_name(conn, other["id"], "denn")


def test_sql_in_a_name_is_stored_as_plain_text(conn):
    name = "Robert'); DROP TABLE rounds;--"
    me = named(conn, name)
    assert store.player_for_google(conn, f"google-{name}")["name"] == name
    store.save_round(conn, me, "test", saved(2))  # the rounds table is still there
    assert store.best_score(conn, me) == 2


def test_best_score_counts_tests_only(conn):
    me = named(conn, "me")
    assert store.best_score(conn, me) is None
    store.save_round(conn, me, "practice", saved(9))
    assert store.best_score(conn, me) is None
    store.save_round(conn, me, "test", saved(3, wrong=2))
    store.save_round(conn, me, "test", saved(5))
    store.save_round(conn, me, "test", saved(4))
    assert store.best_score(conn, me) == 5


def test_history_is_newest_first_and_capped_at_ten(conn):
    me = named(conn, "me")
    for score in range(12):
        store.save_round(conn, me, "test", saved(score))
    history = store.history(conn, me)
    assert history["count"] == 12
    assert history["best"] == 11
    assert [r["score"] for r in history["recent"]] == list(range(11, 1, -1))
    assert history["recent"][0]["at"].endswith("+00:00")


def test_player_attempts_come_back_as_records(conn):
    me, other = named(conn, "me"), named(conn, "other")
    mine = saved(2, wrong=1)
    store.save_round(conn, me, "practice", mine)
    store.save_round(conn, other, "test", saved(4))
    back = store.player_attempts(conn, me)
    assert len(back) == 3
    for key in ["question_id", "text", "category", "strategy", "difficulty", "answer", "given",
                "correct", "skipped", "gave_up", "wrong_tries", "time_ms"]:
        assert [a[key] for a in back] == [a[key] for a in mine], key
    assert {a["mode"] for a in back} == {"practice"}


def test_leaderboard_is_best_score_per_named_player(conn):
    amy, bob, cat = named(conn, "amy"), named(conn, "Bob"), named(conn, "cat")
    dan = named(conn, "dan")
    store.save_round(conn, amy, "test", saved(3))
    store.save_round(conn, amy, "test", saved(6))
    store.save_round(conn, bob, "test", saved(6))
    store.save_round(conn, cat, "test", saved(8))
    store.save_round(conn, dan, "practice", saved(9))  # no test: not on the board
    assert store.leaderboard(conn) == [
        {"id": cat, "name": "cat", "best": 8},
        {"id": amy, "name": "amy", "best": 6},
        {"id": bob, "name": "Bob", "best": 6},
    ]


def test_leaderboard_shows_the_top_ten(conn):
    for score in range(12):
        store.save_round(conn, named(conn, f"p{score:02}"), "test", saved(score))
    assert [row["best"] for row in store.leaderboard(conn)] == list(range(11, 1, -1))


def test_rounds_need_a_real_player_and_mode(conn):
    me = named(conn, "me")
    with pytest.raises(sqlite3.IntegrityError):
        store.save_round(conn, me + 1, "test", saved(1))
    with pytest.raises(sqlite3.IntegrityError):
        store.save_round(conn, me, "free", saved(1))
    assert store.history(conn, me)["count"] == 0  # neither left a round behind


def test_an_empty_test_is_saved_with_score_0(conn):
    me = named(conn, "me")
    store.save_round(conn, me, "test", [])
    history = store.history(conn, me)
    assert (history["count"], history["best"]) == (1, 0)
    assert store.player_attempts(conn, me) == []


def test_sessions_find_their_player(conn):
    me = named(conn, "me")
    token = store.create_session(conn, me)
    assert len(token) >= 40
    assert store.session_player(conn, token) == {"id": me, "name": "me"}


def test_only_a_hash_of_the_token_is_stored(conn):
    token = store.create_session(conn, named(conn, "me"))
    stored = [row[0] for row in conn.execute("SELECT token_hash FROM sessions")]
    assert stored == [hashlib.sha256(token.encode()).hexdigest()]


def test_ended_expired_and_unknown_sessions_find_nobody(conn):
    me = named(conn, "me")
    ended = store.create_session(conn, me)
    store.end_session(conn, ended)
    expired = store.create_session(conn, me)
    with conn:
        conn.execute("UPDATE sessions SET expires_at = ?", (LONG_AGO,))
    for token in [ended, expired, "made-up", ""]:
        assert store.session_player(conn, token) is None


def test_an_oauth_state_works_once(conn):
    store.save_oauth_state(conn, "s1", "v1")
    assert store.take_oauth_state(conn, "s1") == "v1"
    assert store.take_oauth_state(conn, "s1") is None
    assert store.take_oauth_state(conn, "never-made") is None


def test_an_expired_oauth_state_is_refused(conn):
    store.save_oauth_state(conn, "s1", "v1")
    with conn:
        conn.execute("UPDATE oauth_states SET expires_at = ?", (LONG_AGO,))
    assert store.take_oauth_state(conn, "s1") is None


def test_data_survives_reconnecting(tmp_path):
    path = tmp_path / "keep.db"
    first = store.connect(path)
    me = named(first, "me")
    first.close()
    second = store.connect(path)
    assert store.player_for_google(second, "google-me") == {"id": me, "name": "me"}
    second.close()


def test_db_path_comes_from_MENTAL_DB(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAL_DB", str(tmp_path / "x.db"))
    assert store.db_path() == tmp_path / "x.db"
    monkeypatch.delenv("MENTAL_DB")
    assert store.db_path() == Path.home() / ".mental" / "mental.db"


def test_a_database_from_a_newer_version_is_refused(tmp_path):
    path = tmp_path / "newer.db"
    conn = store.connect(path)
    conn.execute("PRAGMA user_version = 3")
    conn.close()
    with pytest.raises(RuntimeError, match="newer version"):
        store.connect(path)


# v1.2's tables, cut down to what the upgrade touches, with one player and one round in them
V1_DATABASE = """
CREATE TABLE players (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, created_at TEXT NOT NULL);
CREATE TABLE rounds (id INTEGER PRIMARY KEY, player_id INTEGER NOT NULL REFERENCES players(id),
                     mode TEXT NOT NULL, score INTEGER NOT NULL, finished_at TEXT NOT NULL);
CREATE TABLE attempts (id INTEGER PRIMARY KEY, round_id INTEGER NOT NULL REFERENCES rounds(id), question_id TEXT NOT NULL);
INSERT INTO players VALUES (1, 'old player', '2026-10-21T10:00:00+00:00');
INSERT INTO rounds VALUES (1, 1, 'test', 30, '2026-10-21T10:00:00+00:00');
PRAGMA user_version = 1;
"""


def test_upgrading_a_v1_database_backs_it_up_and_clears_old_players(tmp_path):
    path = tmp_path / "mental.db"
    old = sqlite3.connect(path)
    old.executescript(V1_DATABASE)
    old.close()
    conn = store.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM rounds").fetchone()[0] == 0
    named(conn, "me")  # the new tables work
    conn.close()
    backup = sqlite3.connect(tmp_path / "mental.db.v1-backup")
    assert backup.execute("SELECT name FROM players").fetchall() == [("old player",)]
    assert backup.execute("PRAGMA user_version").fetchone()[0] == 1
    backup.close()
