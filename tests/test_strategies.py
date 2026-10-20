import random

import pytest

from mental.engine.generate import CATEGORIES, make_question, make_questions
from mental.engine.strategies import STRATEGIES


def evaluate(expr):
    """Turn display maths ('1,234 × 2', '−5', '10% of 340') into Python and run it."""
    expr = expr.replace(",", "").replace("−", "-").replace("×", "*").replace("÷", "/")
    return eval(expr.replace("% of ", "/100*"))


CASES = [(sid, level) for sid, s in STRATEGIES.items() for level in s["difficulties"]]


@pytest.mark.parametrize("strategy_id, difficulty", CASES)
def test_strategy_maths_is_true(strategy_id, difficulty):
    make = STRATEGIES[strategy_id]["make"]
    for seed in range(300):
        text, answer, hints, steps = make(random.Random(seed), difficulty)
        assert type(answer) is int
        assert abs(answer) <= 99_999
        if "?" in text:
            left, right = text.split(" = ")
            assert evaluate(left) == evaluate(right.replace("?", str(answer))), text
        else:
            assert evaluate(text) == answer, text
        assert len(hints) == 2
        for h in hints:
            sides = h.split(" = ")
            assert len(sides) == 1 or sides[0] != sides[1], f"pointless hint: {h}"
        for step in steps:
            left, right = step.split(" = ")
            assert evaluate(left) == evaluate(right), f"{text}: {step}"
        assert evaluate(steps[-1].split(" = ")[1]) == answer, text


def test_strategy_categories_are_known():
    for s in STRATEGIES.values():
        assert s["category"] in CATEGORIES


def test_same_seed_same_question():
    assert make_question("subtraction", 2, 42) == make_question("subtraction", 2, 42)


def test_make_questions_uses_only_given_categories():
    questions = make_questions(["addition", "division"], 1, 50, seed=7)
    assert len(questions) == 50
    assert {q.category for q in questions} <= {"addition", "division"}


def test_unknown_category_is_rejected():
    with pytest.raises(ValueError):
        make_question("astrology", 1, 1)
