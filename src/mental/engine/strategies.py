"""Question generators.

Each strategy is a function (rng, difficulty) -> (text, answer, steps).
It picks numbers that suit one mental trick and writes the worked method for them.
Every step must be a true sum written as "<sum> = <result>" (the tests check this).
No question or step uses 0 or 1 as a number: those sums are pointless.
"""


def fmt(n):
    """1234 -> '1,234'. Minus stays a plain "-": the pixel font has no "−" glyph."""
    return f"{n:,}"


def random_number(rng, digits):
    return rng.randint(10 ** (digits - 1), 10**digits - 1)


def second_number(rng, difficulty):
    """The number being added or taken away in the basic sums.

    It never ends in 1 (the last step would be "+ 1"), never uses the top value
    (so subtraction has room for a bigger first number), and is only round
    (30, 500) at level 1, where "+ 30" belongs.
    """
    digits = difficulty + 1  # level 1: 2 digits, 2: 3 digits, 3: 4 digits
    while True:
        b = rng.randint(10 ** (digits - 1), 10**digits - 2)
        if b % 10 != 1 and (difficulty == 1 or b % 10 != 0):
            return b


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
        op = "-" if subtract else "+"
        steps.append(f"{fmt(total)} {op} {fmt(part)} = {fmt(new)}")
        total = new
    return steps


# --- addition -------------------------------------------------------------


def basic_add(rng, difficulty):
    a, b = random_number(rng, difficulty + 1), second_number(rng, difficulty)
    return f"{fmt(a)} + {fmt(b)}", a + b, chunk_steps(a, place_parts(b))


def near_round(rng, difficulty):
    """A number just under a round one, e.g. 197 = 200 - 3. Returns (round, off)."""
    if difficulty == 2:
        return rng.choice(range(100, 1000, 100)), rng.randint(1, 4)
    return rng.choice(range(100, 10000, 100)), rng.randint(1, 9)


def near_round_add(rng, difficulty):
    round_, off = near_round(rng, difficulty)
    b = round_ - off
    a = random_number(rng, difficulty + 1)
    steps = [
        f"{fmt(a)} + {fmt(round_)} = {fmt(a + round_)}",
        f"{fmt(a + round_)} - {off} = {fmt(a + b)}",
    ]
    return f"{fmt(a)} + {fmt(b)}", a + b, steps


def signed_add(rng, difficulty):
    x, y = random_number(rng, rng.choice([3, 4])), random_number(rng, rng.choice([3, 4]))
    while y == x:  # -347 + 347 is pointless
        y = random_number(rng, rng.choice([3, 4]))
    answer = y - x
    big, small = max(x, y), min(x, y)
    steps = [
        f"{fmt(big)} - {fmt(small)} = {fmt(big - small)}",
        f"{fmt(-x)} + {fmt(y)} = {fmt(answer)}",
    ]
    return f"{fmt(-x)} + {fmt(y)}", answer, steps


# --- subtraction ----------------------------------------------------------


def basic_subtract(rng, difficulty):
    b = second_number(rng, difficulty)
    a = rng.randint(b + 1, 10 ** (difficulty + 1) - 1)  # never x - x
    return f"{fmt(a)} - {fmt(b)}", a - b, chunk_steps(a, place_parts(b), subtract=True)


def near_round_subtract(rng, difficulty):
    round_, off = near_round(rng, difficulty)
    b = round_ - off
    a = rng.randint(b + 1, 10 ** (difficulty + 1) - 1)
    steps = [
        f"{fmt(a)} - {fmt(round_)} = {fmt(a - round_)}",
        f"{fmt(a - round_)} + {off} = {fmt(a - b)}",
    ]
    return f"{fmt(a)} - {fmt(b)}", a - b, steps


def signed_subtract(rng, difficulty):
    x, y = random_number(rng, rng.choice([3, 4])), random_number(rng, rng.choice([3, 4]))
    answer = -(x + y)
    steps = [
        f"{fmt(x)} + {fmt(y)} = {fmt(x + y)}",
        f"{fmt(-x)} - {fmt(y)} = {fmt(answer)}",
    ]
    return f"{fmt(-x)} - {fmt(y)}", answer, steps


# --- multiplication -------------------------------------------------------


def basic_multiply(rng, difficulty):
    if difficulty == 1:
        a, b = rng.randint(2, 9), rng.randint(2, 9)
        return f"{a} × {b}", a * b, [f"{a} × {b} = {a * b}"]  # a times-table fact
    a = rng.choice([n for n in range(12, 100) if n % 10 > 1])  # "1 × 6" would be a pointless step
    b = rng.randint(3, 9)
    tens, units = a - a % 10, a % 10
    steps = [
        f"{tens} × {b} = {tens * b}",
        f"{units} × {b} = {units * b}",
        f"{tens * b} + {units * b} = {a * b}",
    ]
    return f"{a} × {b}", a * b, steps


def near_round_multiply(rng, difficulty):
    if difficulty == 2:
        n, m = rng.choice([9, 11, 19, 21]), rng.randint(12, 49)
    else:
        n, m = rng.choice([29, 31, 39, 41, 49, 51, 99, 101]), rng.randint(12, 99)
    round_ = 100 if n > 90 else (n + 1) // 10 * 10
    sign = "+" if n > round_ else "-"
    base = round_ * m
    steps = [f"{round_} × {m} = {fmt(base)}", f"{fmt(base)} {sign} {m} = {fmt(n * m)}"]
    return f"{n} × {m}", n * m, steps


# --- division -------------------------------------------------------------


def basic_divide(rng, difficulty):
    if difficulty == 1:
        b, q = rng.randint(2, 9), rng.randint(2, 9)
        a = b * q
        return f"{a} ÷ {b}", q, [f"{b} × {q} = {a}", f"{a} ÷ {b} = {q}"]
    b = rng.randint(3, 9)
    q = rng.choice([n for n in range(12, 31) if n % 10 > 1])  # "20 + 1" would be a pointless step
    a = b * q
    tens = q - q % 10
    first, rest = b * tens, a - b * tens
    steps = [
        f"{first} ÷ {b} = {tens}",
        f"{rest} ÷ {b} = {q - tens}",
        f"{tens} + {q - tens} = {q}",
    ]
    return f"{a} ÷ {b}", q, steps


def divide_by_5(rng, difficulty):
    q = rng.randint(12, 400)
    a = 5 * q
    steps = [f"{fmt(a)} × 2 = {fmt(2 * a)}", f"{fmt(2 * a)} ÷ 10 = {fmt(q)}"]
    return f"{fmt(a)} ÷ 5", q, steps


def divide_by_25(rng, difficulty):
    q = rng.randint(12, 400)
    a = 25 * q
    steps = [f"{fmt(a)} × 4 = {fmt(4 * a)}", f"{fmt(4 * a)} ÷ 100 = {fmt(q)}"]
    return f"{fmt(a)} ÷ 25", q, steps


# --- percentages ----------------------------------------------------------


def percent_10(rng, difficulty):
    k = rng.randint(2, 99)
    base = 10 * k
    return f"10% of {fmt(base)}", k, [f"{fmt(base)} ÷ 10 = {k}"]


def percent_25(rng, difficulty):
    k = rng.randint(5, 250)
    base = 4 * k
    steps = [f"{fmt(base)} ÷ 2 = {fmt(2 * k)}", f"{fmt(2 * k)} ÷ 2 = {fmt(k)}"]
    return f"25% of {fmt(base)}", k, steps


def percent_15(rng, difficulty):
    k = rng.randint(2, 99)
    base = 20 * k  # a multiple of 20 keeps 5% a whole number
    ten, five = 2 * k, k
    steps = [f"{fmt(base)} ÷ 10 = {ten}", f"{ten} ÷ 2 = {five}", f"{ten} + {five} = {ten + five}"]
    return f"15% of {fmt(base)}", ten + five, steps


# --- relationships --------------------------------------------------------


def double_halve(rng, difficulty):
    if difficulty == 3:
        a, b = rng.randint(4, 30), 3 * rng.randint(2, 15)
        c, d = a * 3, b // 3
        steps = [f"{a} × 3 = {c}", f"{b} ÷ 3 = {d}"]
    else:
        a = 2 * rng.randint(2, 20 if difficulty == 1 else 49)
        b = rng.randint(3, 15 if difficulty == 1 else 30)
        c, d = a // 2, b * 2
        steps = [f"{a} ÷ 2 = {c}", f"{b} × 2 = {d}"]
    return f"{a} × {b} = {c} × ?", d, steps


STRATEGIES = {
    "basic_add": {"category": "addition", "difficulties": [1, 2, 3], "make": basic_add},
    "near_round_add": {"category": "addition", "difficulties": [2, 3], "make": near_round_add},
    "signed_add": {"category": "addition", "difficulties": [3], "make": signed_add},
    "basic_subtract": {"category": "subtraction", "difficulties": [1, 2, 3], "make": basic_subtract},
    "near_round_subtract": {"category": "subtraction", "difficulties": [2, 3], "make": near_round_subtract},
    "signed_subtract": {"category": "subtraction", "difficulties": [3], "make": signed_subtract},
    "basic_multiply": {"category": "multiplication", "difficulties": [1, 2], "make": basic_multiply},
    "near_round_multiply": {"category": "multiplication", "difficulties": [2, 3], "make": near_round_multiply},
    "basic_divide": {"category": "division", "difficulties": [1, 2], "make": basic_divide},
    "divide_by_5": {"category": "division", "difficulties": [2], "make": divide_by_5},
    "divide_by_25": {"category": "division", "difficulties": [3], "make": divide_by_25},
    "percent_10": {"category": "percentage", "difficulties": [1], "make": percent_10},
    "percent_25": {"category": "percentage", "difficulties": [2], "make": percent_25},
    "percent_15": {"category": "percentage", "difficulties": [3], "make": percent_15},
    "double_halve": {"category": "relationship", "difficulties": [1, 2, 3], "make": double_halve},
}
