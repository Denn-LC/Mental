"""Re-check attempt records that come back from the browser before they are saved.

The browser could send anything, so nothing it says about a question, or about being right,
counts: each question is rebuilt from its id and `correct` is worked out from what was typed.
"""
import re

from mental.engine.generate import make_question


def question_from_id(question_id):
    """'division-2-77' -> the very Question make_question gave out. ValueError if it can't be."""
    try:
        category, difficulty, seed = question_id.rsplit("-", 2)
        seed = int(seed)
        if not (0 <= seed < 2**32):
            raise ValueError(f"not a question id: {question_id!r}")
        question = make_question(category, int(difficulty), seed)
    except ValueError:
        raise ValueError(f"not a question id: {question_id!r}") from None
    if question.id != question_id:  # "1_000" or " 5" parse as numbers but are not how ids are written
        raise ValueError(f"not a question id: {question_id!r}")
    return question


def parse_answer(text):
    """As app.js's parseAnswer: '-465' and '−465' are -465; anything else is None."""
    clean = text.replace("−", "-")
    return int(clean) if re.fullmatch(r"-?[0-9]+", clean) else None


def checked(attempt):
    """A copy of an attempt record whose question fields and `correct` come from the server.

    ValueError if the id isn't a real question or the text doesn't match it.
    """
    question = question_from_id(attempt["question_id"])
    if attempt["text"] != question.text:
        raise ValueError(f"{attempt['question_id']} is {question.text!r}, not {attempt['text']!r}")
    answered = not attempt["skipped"] and not attempt["gave_up"]
    return {
        **attempt,
        "seed": question.seed,
        "category": question.category,
        "strategy": question.strategy,
        "difficulty": question.difficulty,
        "answer": question.answer,
        "correct": answered and parse_answer(attempt["given"]) == question.answer,
    }
