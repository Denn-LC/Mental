import pytest

from mental.engine.check import checked, parse_answer, question_from_id
from mental.engine.generate import make_question
from records import record

Q = make_question("division", 2, 77)


def test_question_is_rebuilt_from_its_id():
    assert question_from_id(Q.id) == Q


def test_right_answer_is_correct_whatever_the_browser_says():
    assert checked(record(Q, str(Q.answer), correct=False))["correct"] is True


def test_wrong_answer_is_not_correct_whatever_the_browser_says():
    assert checked(record(Q, str(Q.answer + 1), correct=True))["correct"] is False


def test_given_up_or_skipped_is_never_correct():
    assert checked(record(Q, str(Q.answer), gave_up=True, correct=True))["correct"] is False
    assert checked(record(Q, str(Q.answer), skipped=True, correct=True))["correct"] is False


def test_question_fields_come_from_the_server():
    a = checked(record(Q, "5", answer=5, strategy="made_up", difficulty=3, category="addition", seed=1))
    assert (a["answer"], a["strategy"], a["difficulty"], a["category"], a["seed"]) == \
        (Q.answer, Q.strategy, Q.difficulty, Q.category, Q.seed)


def test_changed_text_is_rejected():
    with pytest.raises(ValueError):
        checked(record(Q, "1", text="2 + 2"))


@pytest.mark.parametrize("question_id", ["", "addition", "addition-1", "addition-9-5", "astrology-1-5", "addition-1-1_000", f"addition-1-{2**32}"])
def test_bad_question_ids_are_rejected(question_id):
    with pytest.raises(ValueError):
        question_from_id(question_id)


def test_parse_answer():
    assert parse_answer("465") == 465
    assert parse_answer("-465") == -465
    assert parse_answer("−465") == -465
    assert parse_answer("") is None
    assert parse_answer("4 5") is None
    assert parse_answer("٤٥") is None  # digits from other scripts are not answers


def test_negative_answers_count_with_either_minus():
    q = make_question("addition", 3, 5)  # -6,874 + 960
    assert q.answer < 0
    for typed in [str(q.answer), str(q.answer).replace("-", "−")]:
        assert checked(record(q, typed))["correct"] is True
