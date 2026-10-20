import random

from mental.engine.question import Question
from mental.engine.strategies import STRATEGIES

CATEGORIES = ["addition", "subtraction", "multiplication", "division", "percentage", "relationship"]


def strategies_for(category, difficulty):
    return [sid for sid, s in STRATEGIES.items() if s["category"] == category and difficulty in s["difficulties"]]


def make_question(category, difficulty, seed):
    """The same (category, difficulty, seed) always gives the same question."""
    options = strategies_for(category, difficulty)
    if not options:
        raise ValueError(f"no {category} questions at level {difficulty}")
    rng = random.Random(seed)
    strategy = rng.choice(options)
    text, answer, steps = STRATEGIES[strategy]["make"](rng, difficulty)
    return Question(
        id=f"{category}-{difficulty}-{seed}",
        seed=seed,
        text=text,
        answer=answer,
        category=category,
        strategy=strategy,
        difficulty=difficulty,
        steps=steps,
    )


def make_questions(categories, difficulty, count, seed=None):
    """count questions, each from a random one of categories that has questions at this level."""
    usable = [c for c in categories if strategies_for(c, difficulty)]
    if not usable:
        raise ValueError(f"no questions for {', '.join(categories)} at level {difficulty}")
    rng = random.Random(seed)
    return [make_question(rng.choice(usable), difficulty, rng.randrange(2**32)) for _ in range(count)]
