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


def make_questions(categories, difficulties, count, seed=None):
    """count questions, each from a random (category, level) pair that has questions."""
    pairs = [(c, d) for c in categories for d in difficulties if strategies_for(c, d)]
    if not pairs:
        raise ValueError(f"no questions for {', '.join(categories)} at level {difficulties}")
    rng = random.Random(seed)
    return [make_question(*rng.choice(pairs), rng.randrange(2**32)) for _ in range(count)]
