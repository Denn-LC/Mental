import random
import re

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
        text, answer, steps = make(random.Random(seed), difficulty)
        assert type(answer) is int
        assert abs(answer) <= 99_999
        if "?" in text:
            left, right = text.split(" = ")
            assert evaluate(left) == evaluate(right.replace("?", str(answer))), text
        else:
            assert evaluate(text) == answer, text
        assert "−" not in text + "".join(steps), "the pixel font has no − glyph; use -"
        for step in steps:
            left, right = step.split(" = ")
            assert evaluate(left) == evaluate(right), f"{text}: {step}"
        assert evaluate(steps[-1].split(" = ")[1]) == answer, text


def numbers_in(expr):
    """'1,234 + 17 = 1,251' -> [1234, 17, 1251]"""
    return [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", expr)]


# "467 + 199 → 467 + 200 − 1": taking the 1 back off is the trick itself, not a pointless step
ONE_IS_THE_TRICK = {"near_round_add", "near_round_subtract"}


@pytest.mark.parametrize("strategy_id, difficulty", CASES)
def test_no_pointless_zero_or_one(strategy_id, difficulty):
    make = STRATEGIES[strategy_id]["make"]
    for seed in range(300):
        text, answer, steps = make(random.Random(seed), difficulty)
        assert not {0, 1} & set(numbers_in(text.replace("?", ""))), text
        if strategy_id not in ONE_IS_THE_TRICK:
            for step in steps:
                left = step.split(" = ")[0]
                assert not {0, 1} & set(numbers_in(left)), f"{text}: {step}"


def second_numbers(strategy_id, difficulty):
    """The number added or taken away, over 300 seeds."""
    make = STRATEGIES[strategy_id]["make"]
    return [numbers_in(make(random.Random(seed), difficulty)[0])[1] for seed in range(300)]


def test_round_numbers_only_at_level_1():
    for strategy_id in ["basic_add", "basic_subtract"]:
        assert any(b % 10 == 0 for b in second_numbers(strategy_id, 1)), strategy_id
        for difficulty in [2, 3]:
            assert all(b % 10 != 0 for b in second_numbers(strategy_id, difficulty)), strategy_id


def test_signed_add_never_cancels_to_zero():
    from mental.engine.strategies import signed_add

    for seed in range(5000):
        text, answer, steps = signed_add(random.Random(seed), 3)
        assert answer != 0, text


def test_strategy_categories_are_known():
    for s in STRATEGIES.values():
        assert s["category"] in CATEGORIES


def test_same_seed_same_question():
    assert make_question("subtraction", 2, 42) == make_question("subtraction", 2, 42)


def test_make_questions_uses_only_given_categories():
    questions = make_questions(["addition", "division"], [1], 50, seed=7)
    assert len(questions) == 50
    assert {q.category for q in questions} <= {"addition", "division"}


def test_mixed_levels_give_easy_and_hard_questions():
    questions = make_questions(CATEGORIES, [1, 2, 3], 600, seed=3)
    assert {q.difficulty for q in questions} == {1, 2, 3}
    percent = {q.strategy for q in questions if q.category == "percentage"}
    relationship = {q.strategy for q in questions if q.category == "relationship"}
    assert percent == {"percent_10", "percent_25", "percent_15"}
    assert relationship == {"double_halve", "balance_sum"}


def test_unknown_category_is_rejected():
    with pytest.raises(ValueError):
        make_question("astrology", 1, 1)


def test_addition_and_subtraction_have_tricks_at_levels_2_and_3():
    from mental.engine.generate import strategies_for

    assert "near_round_add" in strategies_for("addition", 2)
    assert {"near_round_add", "signed_add"} <= set(strategies_for("addition", 3))
    assert "near_round_subtract" in strategies_for("subtraction", 2)
    assert {"near_round_subtract", "signed_subtract"} <= set(strategies_for("subtraction", 3))


def test_every_category_has_questions_at_every_level():
    for category in CATEGORIES:
        for difficulty in [1, 2, 3]:
            make_question(category, difficulty, seed=1)


def test_basic_subtract_never_asks_x_minus_x():
    from mental.engine.strategies import basic_subtract

    for difficulty in [1, 2, 3]:
        for seed in range(2000):
            text, answer, steps = basic_subtract(random.Random(seed), difficulty)
            assert answer != 0, text
