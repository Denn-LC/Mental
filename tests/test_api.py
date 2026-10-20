from fastapi.testclient import TestClient

from mental.web.app import app

client = TestClient(app)


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
