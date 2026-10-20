"""Question generators.

Each strategy is a function (rng, difficulty) -> (text, answer, hints, steps).
It picks numbers that suit one mental trick and writes the explanation for them.
Every step must be a true sum written as "<sum> = <result>" (the tests check this).
"""


def fmt(n):
    """1234 -> '1,234' and -5 -> '−5' (a real minus sign, for display)."""
    return f"{n:,}".replace("-", "−")


def random_number(rng, digits):
    return rng.randint(10 ** (digits - 1), 10**digits - 1)


def place_parts(n):
    """2917 -> [2000, 900, 10, 7]"""
    s = str(n)
    return [int(d) * 10 ** (len(s) - 1 - i) for i, d in enumerate(s) if d != "0"]


def chunk_steps(start, parts, subtract=False):
    """Add (or take away) parts one at a time: ['4,382 + 2,000 = 6,382', ...]"""
    steps = []
    total = start
    for part in parts:
        new = total - part if subtract else total + part
        op = "−" if subtract else "+"
        steps.append(f"{fmt(total)} {op} {fmt(part)} = {fmt(new)}")
        total = new
    return steps


def basic_add(rng, difficulty):
    digits = difficulty + 1  # level 1: 2 digits, 2: 3 digits, 3: 4 digits
    a, b = random_number(rng, digits), random_number(rng, digits)
    b += 0 if b % 10 else 1  # a round b would make the hint pointless
    parts = place_parts(b)
    hints = [
        f"Add {fmt(b)} one place value at a time.",
        f"{fmt(b)} = {' + '.join(fmt(p) for p in parts)}",
    ]
    return f"{fmt(a)} + {fmt(b)}", a + b, hints, chunk_steps(a, parts)


def basic_subtract(rng, difficulty):
    digits = difficulty + 1
    b = random_number(rng, digits)
    b += 0 if b % 10 else 1  # a round b would make the hint pointless
    a = rng.randint(b, 10**digits - 1)
    parts = place_parts(b)
    hints = [
        f"Take {fmt(b)} away one place value at a time.",
        f"{fmt(b)} = {' + '.join(fmt(p) for p in parts)}",
    ]
    return f"{fmt(a)} − {fmt(b)}", a - b, hints, chunk_steps(a, parts, subtract=True)


def basic_multiply(rng, difficulty):
    if difficulty == 1:
        a, b = rng.randint(2, 9), rng.randint(2, 9)
        hints = [
            "This is a times-table fact.",
            f"{a} × {b - 1} = {a * (b - 1)}, then add one more {a}.",
        ]
        steps = [f"{a} × {b - 1} = {a * (b - 1)}", f"{a * (b - 1)} + {a} = {a * b}"]
        return f"{a} × {b}", a * b, hints, steps
    a = rng.choice([n for n in range(12, 100) if n % 10])
    b = rng.randint(3, 9)
    tens, units = a - a % 10, a % 10
    hints = [
        f"Split {a} into tens and units.",
        f"{a} × {b} = {tens} × {b} + {units} × {b}",
    ]
    steps = [
        f"{tens} × {b} = {tens * b}",
        f"{units} × {b} = {units * b}",
        f"{tens * b} + {units * b} = {a * b}",
    ]
    return f"{a} × {b}", a * b, hints, steps


def basic_divide(rng, difficulty):
    if difficulty == 1:
        b, q = rng.randint(2, 9), rng.randint(2, 9)
        a = b * q
        hints = ["Run the times table backwards.", f"{b} × ? = {a}"]
        steps = [f"{b} × {q} = {a}", f"{a} ÷ {b} = {q}"]
        return f"{a} ÷ {b}", q, hints, steps
    b = rng.randint(3, 9)
    q = rng.choice([n for n in range(12, 31) if n % 10])
    a = b * q
    tens = q - q % 10
    first, rest = b * tens, a - b * tens
    hints = [f"Split {a} into easy chunks of {b}.", f"{a} = {first} + {rest}"]
    steps = [
        f"{first} ÷ {b} = {tens}",
        f"{rest} ÷ {b} = {q - tens}",
        f"{tens} + {q - tens} = {q}",
    ]
    return f"{a} ÷ {b}", q, hints, steps


STRATEGIES = {
    "basic_add": {"category": "addition", "difficulties": [1, 2, 3], "make": basic_add},
    "basic_subtract": {"category": "subtraction", "difficulties": [1, 2, 3], "make": basic_subtract},
    "basic_multiply": {"category": "multiplication", "difficulties": [1, 2], "make": basic_multiply},
    "basic_divide": {"category": "division", "difficulties": [1, 2], "make": basic_divide},
}
