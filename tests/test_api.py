import pytest
from fastapi.testclient import TestClient

from mental.engine.generate import make_question
from mental.web.app import app
from records import record, records

client = TestClient(app)


def new_player(name="me"):
    return client.post("/api/players", json={"name": name}).json()["id"]


def save(player_id, mode, attempts):
    return client.post("/api/rounds", json={"player_id": player_id, "mode": mode, "attempts": attempts})


def test_questions_for_one_category():
    response = client.get("/api/questions", params={"category": "addition", "difficulty": 1, "count": 5})
    assert response.status_code == 200
    questions = response.json()
    assert len(questions) == 5
    assert {q["category"] for q in questions} == {"addition"}
    assert {"id", "seed", "text", "answer", "strategy", "difficulty", "steps"} <= questions[0].keys()


def test_questions_for_a_category_list():
    response = client.get("/api/questions", params={"category": "addition,division", "count": 40})
    assert {q["category"] for q in response.json()} <= {"addition", "division"}


def test_unknown_category_is_400():
    assert client.get("/api/questions", params={"category": "astrology"}).status_code == 400


def test_difficulty_out_of_range_is_422():
    assert client.get("/api/questions", params={"difficulty": 4}).status_code == 422


def test_mixed_difficulty_mixes_levels():
    response = client.get("/api/questions", params={"difficulty": "mixed", "count": 200})
    assert response.status_code == 200
    assert {q["difficulty"] for q in response.json()} == {1, 2, 3}


def test_difficulty_that_is_not_a_level_is_422():
    assert client.get("/api/questions", params={"difficulty": "hard"}).status_code == 422


def test_page_is_served():
    response = client.get("/")
    assert response.status_code == 200
    assert "mental" in response.text


def test_add_and_list_players():
    assert client.post("/api/players", json={"name": "Denn"}).json()["name"] == "Denn"
    client.post("/api/players", json={"name": "amy"})
    assert [p["name"] for p in client.get("/api/players").json()] == ["amy", "Denn"]


def test_taken_name_is_409():
    new_player("Denn")
    assert client.post("/api/players", json={"name": "DENN"}).status_code == 409


@pytest.mark.parametrize("name", ["", " me", "me ", "a" * 17, "<b>hi</b>", "x'; DROP TABLE players;--"])
def test_bad_names_are_422(name):
    assert client.post("/api/players", json={"name": name}).status_code == 422


def test_saving_a_round_returns_its_summary():
    response = save(new_player(), "practice", records(3, wrong=1))
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["overall"]["score"] == 3
    assert body["summary"]["overall"]["skipped"] == 1
    assert body["best"] is None  # practice has no best


def test_the_server_decides_what_is_correct():
    q = make_question("multiplication", 2, 5)
    lie = record(q, str(q.answer + 1), correct=True)
    assert save(new_player(), "test", [lie]).json()["summary"]["overall"]["score"] == 0


def test_test_rounds_report_the_best():
    me = new_player()
    assert save(me, "test", records(4)).json()["best"] == {"previous": None, "best": 4}
    assert save(me, "test", records(6)).json()["best"] == {"previous": 4, "best": 6}
    assert save(me, "test", records(5)).json()["best"] == {"previous": 6, "best": 6}


def test_round_for_unknown_player_is_404():
    assert save(999, "test", records(1)).status_code == 404


def test_attempt_that_does_not_match_its_question_is_400():
    tampered = records(1)
    tampered[0]["text"] = "2 + 2"
    assert save(new_player(), "test", tampered).status_code == 400


def test_bad_attempt_is_422():
    bad = records(1)
    bad[0]["time_ms"] = -5
    assert save(new_player(), "test", bad).status_code == 422


def test_too_many_attempts_is_422():
    assert save(new_player(), "test", records(1) * 1001).status_code == 422


def test_stats_for_a_player():
    me = new_player()
    save(me, "test", records(2, wrong=1))
    save(me, "practice", records(3))
    stats = client.get(f"/api/players/{me}/stats").json()
    assert stats["tests"]["count"] == 1
    assert stats["tests"]["best"] == 2
    assert stats["by_category"]["addition"]["count"] == 6
    assert stats["by_category"]["addition"]["score"] == 5


def test_stats_for_unknown_player_is_404():
    assert client.get("/api/players/999/stats").status_code == 404


def test_leaderboard_endpoint():
    me, you = new_player("me"), new_player("you")
    save(me, "test", records(2))
    save(you, "test", records(3))
    assert client.get("/api/leaderboard").json() == [
        {"id": you, "name": "you", "best": 3},
        {"id": me, "name": "me", "best": 2},
    ]


def test_pages_and_answers_are_not_cached():
    for path in ["/", "/app.js", "/api/players"]:
        assert client.get(path).headers["cache-control"] == "no-cache", path
