import sqlite3
from pathlib import Path

import pytest

from mental import store
from mental.engine.check import checked
from records import records


@pytest.fixture
def conn(tmp_path):
    conn = store.connect(tmp_path / "test.db")
    yield conn
    conn.close()


def saved(right, wrong=0):
    """Checked records, as the API hands them to the store."""
    return [checked(a) for a in records(right, wrong)]


def test_new_database_has_schema_version_1(conn):
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1 == store.SCHEMA_VERSION


def test_players_are_listed_by_name(conn):
    store.add_player(conn, "zed")
    store.add_player(conn, "Amy")
    assert [p["name"] for p in store.players(conn)] == ["Amy", "zed"]


def test_names_are_unique_ignoring_case(conn):
    store.add_player(conn, "Denn")
    with pytest.raises(store.NameTaken):
        store.add_player(conn, "denn")


def test_sql_in_a_name_is_stored_as_plain_text(conn):
    name = "Robert'); DROP TABLE rounds;--"
    player = store.add_player(conn, name)
    assert store.players(conn) == [player]
    assert player["name"] == name
    store.save_round(conn, player["id"], "test", saved(2))  # the rounds table is still there
    assert store.best_score(conn, player["id"]) == 2


def test_best_score_counts_tests_only(conn):
    me = store.add_player(conn, "me")["id"]
    assert store.best_score(conn, me) is None
    store.save_round(conn, me, "practice", saved(9))
    assert store.best_score(conn, me) is None
    store.save_round(conn, me, "test", saved(3, wrong=2))
    store.save_round(conn, me, "test", saved(5))
    store.save_round(conn, me, "test", saved(4))
    assert store.best_score(conn, me) == 5


def test_history_is_newest_first_and_capped_at_ten(conn):
    me = store.add_player(conn, "me")["id"]
    for score in range(12):
        store.save_round(conn, me, "test", saved(score))
    history = store.history(conn, me)
    assert history["count"] == 12
    assert history["best"] == 11
    assert [r["score"] for r in history["recent"]] == list(range(11, 1, -1))
    assert history["recent"][0]["at"].endswith("+00:00")


def test_player_attempts_come_back_as_records(conn):
    me = store.add_player(conn, "me")["id"]
    other = store.add_player(conn, "other")["id"]
    mine = saved(2, wrong=1)
    store.save_round(conn, me, "practice", mine)
    store.save_round(conn, other, "test", saved(4))
    back = store.player_attempts(conn, me)
    assert len(back) == 3
    for key in ["question_id", "text", "category", "strategy", "difficulty", "answer", "given",
                "correct", "skipped", "gave_up", "wrong_tries", "time_ms"]:
        assert [a[key] for a in back] == [a[key] for a in mine], key
    assert {a["mode"] for a in back} == {"practice"}


def test_leaderboard_is_best_score_per_player(conn):
    amy, bob, cat, dan = (store.add_player(conn, n)["id"] for n in ["amy", "Bob", "cat", "dan"])
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


def test_data_survives_reconnecting(tmp_path):
    path = tmp_path / "keep.db"
    first = store.connect(path)
    store.add_player(first, "me")
    first.close()
    second = store.connect(path)
    assert [p["name"] for p in store.players(second)] == ["me"]
    second.close()


def test_db_path_comes_from_MENTAL_DB(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAL_DB", str(tmp_path / "x.db"))
    assert store.db_path() == tmp_path / "x.db"
    monkeypatch.delenv("MENTAL_DB")
    assert store.db_path() == Path.home() / ".mental" / "mental.db"


def test_rounds_need_a_real_player_and_mode(conn):
    me = store.add_player(conn, "me")["id"]
    with pytest.raises(sqlite3.IntegrityError):
        store.save_round(conn, me + 1, "test", saved(1))
    with pytest.raises(sqlite3.IntegrityError):
        store.save_round(conn, me, "free", saved(1))
    assert store.history(conn, me)["count"] == 0  # neither left a round behind


def test_an_empty_test_is_saved_with_score_0(conn):
    me = store.add_player(conn, "me")["id"]
    store.save_round(conn, me, "test", [])
    history = store.history(conn, me)
    assert (history["count"], history["best"]) == (1, 0)
    assert store.player_attempts(conn, me) == []


def test_leaderboard_shows_the_top_ten(conn):
    for score in range(12):
        player = store.add_player(conn, f"p{score:02}")["id"]
        store.save_round(conn, player, "test", saved(score))
    assert [row["best"] for row in store.leaderboard(conn)] == list(range(11, 1, -1))


def test_a_database_from_a_newer_version_is_refused(tmp_path):
    path = tmp_path / "newer.db"
    conn = store.connect(path)
    conn.execute("PRAGMA user_version = 2")
    conn.close()
    with pytest.raises(RuntimeError, match="newer version"):
        store.connect(path)
