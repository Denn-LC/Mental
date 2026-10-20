from fastapi.testclient import TestClient

from mental.engine.summary import summarise
from mental.web.app import app


def attempt(category="addition", strategy="basic_add", correct=True, skipped=False,
            wrong_tries=(), hints_used=0, time_ms=1000, question_id="q"):
    return {
        "question_id": question_id, "seed": 1, "text": "1 + 1", "category": category,
        "strategy": strategy, "difficulty": 1, "answer": 2, "given": "2" if correct else "",
        "correct": correct, "skipped": skipped, "wrong_tries": list(wrong_tries),
        "hints_used": hints_used, "time_ms": time_ms, "mode": "test",
    }


def test_empty_attempts_do_not_crash():
    summary = summarise([])
    assert summary["overall"] == {"count": 0, "score": 0, "skipped": 0, "accuracy": 0.0, "avg_time_ms": 0}
    assert summary["slowest"] == []


def test_accuracy_counts_only_clean_first_tries():
    attempts = [
        attempt(time_ms=1000),
        attempt(wrong_tries=["3"], time_ms=3000),
        attempt(correct=False, skipped=True, time_ms=9000),
        attempt(hints_used=1, time_ms=2000),
    ]
    overall = summarise(attempts)["overall"]
    assert overall["count"] == 4
    assert overall["score"] == 3
    assert overall["skipped"] == 1
    assert overall["accuracy"] == 0.25
    assert overall["avg_time_ms"] == 2000  # (1000 + 3000 + 2000) / 3 — the skip is left out


def test_grouped_by_category_and_strategy():
    attempts = [
        attempt(category="addition", strategy="basic_add", time_ms=1000),
        attempt(category="division", strategy="divide_by_5", time_ms=5000),
        attempt(category="division", strategy="divide_by_5", time_ms=7000),
    ]
    summary = summarise(attempts)
    assert summary["by_category"]["division"]["avg_time_ms"] == 6000
    assert summary["by_strategy"]["basic_add"]["count"] == 1


def test_slowest_are_ordered_and_capped_at_five():
    attempts = [attempt(question_id=f"q{i}", time_ms=i * 100) for i in range(8)]
    assert summarise(attempts)["slowest"] == ["q7", "q6", "q5", "q4", "q3"]


def test_summary_endpoint():
    response = TestClient(app).post("/api/summary", json=[attempt(), attempt(correct=False, skipped=True)])
    assert response.status_code == 200
    assert response.json()["overall"]["score"] == 1


def test_summary_endpoint_rejects_bad_attempts():
    bad = attempt()
    bad["hints_used"] = 7
    assert TestClient(app).post("/api/summary", json=[bad]).status_code == 422


def test_summary_endpoint_rejects_huge_lists():
    assert TestClient(app).post("/api/summary", json=[attempt()] * 1001).status_code == 413
