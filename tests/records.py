"""Attempt records built the way app.js builds them, for tests."""
from mental.engine.generate import make_question


def record(question, given, **changes):
    """One attempt record for question with `given` typed; `changes` overrides any field."""
    attempt = {
        "question_id": question.id, "seed": question.seed, "text": question.text,
        "category": question.category, "strategy": question.strategy, "difficulty": question.difficulty,
        "answer": question.answer, "given": given, "correct": False, "skipped": False,
        "wrong_tries": [], "gave_up": False, "time_ms": 1500, "mode": "test",
    }
    return {**attempt, **changes}


def records(right, wrong=0):
    """Records for different addition questions: `right` answered correctly, then `wrong` skipped."""
    out = []
    for seed in range(right + wrong):
        q = make_question("addition", 1, seed)
        if seed < right:
            out.append(record(q, str(q.answer), correct=True, time_ms=1000 + seed))
        else:
            out.append(record(q, "", skipped=True, time_ms=1000 + seed))
    return out
