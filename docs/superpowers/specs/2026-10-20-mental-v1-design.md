# mental v1 — design

Date: 2026-10-20 · Branch: `v1.0`

## Goal

A local mental-arithmetic trainer that teaches efficient patterns, not just a random quiz.
Loop: attempt → struggle → solve → understand a better method → measure → improve.

v1 is a simple, polished local prototype. It keeps a clean path toward strategy-based
explanations, personal bests, benchmarks, weakness detection, adaptive practice and
public deployment — without building any of those yet.

## Constraints

- Python + FastAPI, plain HTML/CSS, vanilla JS, uv. Runtime deps: `fastapi`, `uvicorn`. Dev: `pytest`.
- No Docker, JS frameworks, Redis, Postgres, cloud, auth, AI APIs, build step.
- No persistence in v1. Results live in the browser until the tab closes.
- Readable, ordinary code: functions and dataclasses, no class hierarchies or plugin systems.
- Explanations are deterministic, written by strategy code. No LLM.

## Architecture

**Python generates, JS plays.** The server is stateless.

1. JS fetches questions from `GET /api/questions?category=…&difficulty=…&count=…`.
   Each question arrives with its answer, hints and solution steps.
2. JS handles input, timing, checking, streak and builds attempt records.
   Checking is client-side so test mode can accept answers per keystroke without lag.
3. At the end of a test JS posts attempts to `POST /api/summary`; Python returns the stats.

Accepted trade-off: answers are visible in devtools. Irrelevant locally; when public
leaderboards arrive the server re-validates submitted attempts by regenerating questions
from their seed.

```
pyproject.toml
src/mental/
  engine/              # pure Python — never imports FastAPI
    question.py        # Question dataclass
    strategies.py      # one function per strategy + STRATEGIES dict
    generate.py        # pick strategy by category/difficulty, seed rng → Question
    summary.py         # attempts → overall / per-category / per-strategy stats
  web/
    app.py             # FastAPI: two API routes + static files
    static/
      index.html       # one page, both modes
      style.css        # pixel theme, streak heat via --heat
      app.js           # input, timer, checking, attempt records
      fonts/           # Press Start 2P + a monospace, served locally
tests/
  test_strategies.py
  test_summary.py
```

Run with `uv run uvicorn mental.web.app:app --reload`.

## Questions

```python
@dataclass
class Question:
    id: str            # derived from the seed, e.g. "q_8f3a…"
    seed: int          # regenerates this exact question
    text: str          # "615 − 197", "18 × 6 = 9 × ?"
    answer: int
    category: str      # addition | subtraction | multiplication | division | percentage | relationship
    strategy: str      # stable ID, e.g. "near_round_subtract"
    difficulty: int    # 1–3
    hints: list[str]   # [pattern nudge, explicit transformation]
    steps: list[str]   # worked mental method, one line per step
```

Rules for every question:

- Answers are integers; generators choose numbers that make this true (15% of 240, never of 237).
- `|answer| ≤ 99_999`.
- Each strategy has one worked method in v1. Alternative methods for the same question can be
  added later as a new optional field without changing existing ones.

## Strategies

A strategy is a function `(rng, difficulty) -> Question` that picks numbers suited to its trick
and writes the hints and steps alongside them. All are listed in one dict:

```python
STRATEGIES = {
    "near_round_subtract": {"category": "subtraction", "difficulties": [2, 3], "make": near_round_subtract},
    ...
}
```

Adding a strategy = one function + one dict entry. Strategy IDs are permanent once shipped,
because stats will key on them.

### Difficulty

Difficulty is about the trick and how hidden it is, not only number size.

| Level | Meaning |
|---|---|
| 1 | Plain arithmetic, small numbers, no trick needed |
| 2 | One clear trick |
| 3 | Same tricks, less obvious, larger or signed numbers |

Addition / subtraction operand size: level 1 two-digit, level 2 three-digit, level 3 up to four-digit
including signed forms (`−x − y`, `−x + y`).

### v1 strategy set

| ID | Category | Levels | Example | Method |
|---|---|---|---|---|
| `basic_add` | addition | 1–3 | 4,382 + 2,917 | column by column, left to right |
| `near_round_add` | addition | 2–3 | 467 + 198 | + 200 − 2 |
| `signed_add` | addition | 3 | −347 + 812 | bigger magnitude minus smaller, keep its sign |
| `basic_subtract` | subtraction | 1–3 | 7,104 − 2,658 | count up / column |
| `near_round_subtract` | subtraction | 2–3 | 615 − 197, 940 − 94 | − 200 + 3, − 100 + 6 |
| `signed_subtract` | subtraction | 3 | −347 − 812 | add magnitudes, result negative |
| `basic_multiply` | multiplication | 1–2 | 7 × 8, 34 × 6 | split the bigger number |
| `near_round_multiply` | multiplication | 2–3 | 19 × 24, 99 × 13, 21 × 15 | 20 × 24 − 24 |
| `basic_divide` | division | 1–2 | 72 ÷ 8 | times table in reverse |
| `divide_by_5` | division | 2 | 840 ÷ 5 | × 2 ÷ 10 |
| `divide_by_25` | division | 3 | 1,300 ÷ 25 | × 4 ÷ 100 |
| `percent_10` | percentage | 1 | 10% of 340 | ÷ 10 |
| `percent_25` | percentage | 2 | 25% of 360 | ÷ 4 |
| `percent_15` | percentage | 3 | 15% of 240 | 10% + 5% |
| `double_halve` | relationship | 1–3 | 18 × 6 = 9 × ? | halve one side, double the other (level 3: ×3 / ÷3, e.g. 24 × 15 = 36 × ?) |
| `balance_sum` | relationship | 2–3 | 47 + 38 = 50 + ? | what moved from one term moves off the other |

The exact wording of hints and steps is a first draft; the user will review the methods.

## Attempt record

Built by JS, one per question shown. Shape is fixed now so storage and analytics can be added
later without changes:

```js
{ question_id, seed, text, category, strategy, difficulty, answer,
  given: "418",          // final value entered ("" if skipped)
  correct: true,
  skipped: false,
  wrong_tries: ["408"],  // every wrong value submitted; later used for cheat detection
  hints_used: 0,         // 0–2 hints, 3 = saw the solution
  time_ms: 4210,
  mode: "free" | "test" }
```

## Modes

### Free Play

- Choose one category (or mixed) and a difficulty with number keys.
- Enter submits. Wrong → "not quite", stay on the question, value added to `wrong_tries`.
- `H` reveals the next help level: hint 1 → hint 2 → solution steps.
- When correct, the solution steps are shown as reinforcement; Enter goes to the next question.
- Streak counts answers correct on the first try with no hints.

### Test Yourself — 1-minute mixed sprint

- One large question. Typing the correct answer advances immediately (no Enter).
- Enter on a wrong value flashes it and adds it to `wrong_tries`; stay on the question.
- Tab skips.
- At 0:00 JS posts attempts to `/api/summary` and shows results: score, accuracy, average time,
  a per-category table, and the slowest questions with their methods.

### Shared input rules

- The answer box accepts digits and a leading `−`/`-`.
- Fully keyboard-driven; the mouse is never required.

## Summary (`summary.py`)

`summarise(attempts) -> dict` returns overall accuracy and average time, the same per category
and per strategy, and the slowest attempts. A weakness can be low accuracy, slow time, or both,
so both numbers are always reported side by side. No "weak/strong" labels in v1.

## Visual direction

- Dark background, amber/orange accents, Press Start 2P for headings, timer and score; a readable
  monospace for numbers.
- Chunky pixel-style borders built in CSS, with no image assets.
- Streak heat: JS sets `--heat` (0–3) from the current streak; CSS scales accent brightness and glow.
- No animations beyond simple feedback flashes in v1.

## Testing

- `test_strategies.py`: for every strategy and allowed difficulty, across a few hundred seeds:
  the answer equals the true arithmetic, it is an integer, `|answer| ≤ 99_999`, the same seed gives
  the same question, and every step's arithmetic is true.
- `test_summary.py`: small hand-built attempt lists → expected stats.
- The UI is checked by hand in the browser.

## Build stages (app runs after each)

1. uv project; engine with the `basic_*` strategies; tests pass.
2. FastAPI + bare page: Free Play with checking and retry.
3. Hints and solutions; the full v1 strategy set.
4. Test mode: timer, auto-advance, skip, attempt records.
5. `/api/summary` + results screen.
6. Pixel theme, streak heat, keyboard polish.

## Not in v1 (remembered for later)

- **Free Play topic picker**: tick any mix of addition, subtraction, multiplication, division,
  percentages and relationships, plus a difficulty choice. (`/api/questions` should already accept
  a comma-separated `category` list so this is UI-only later.)
- User-based storage: personal bests, history, progress over time (SQLite).
- Benchmarks beyond the 1-minute sprint (5-minute, per-category tests).
- Weakness labels and adaptive question selection.
- Cheat detection (data captured via `wrong_tries`).
- Alternative solution methods per question.
- Quant mode.
- Flames, embers and other animations.
- Deployment.
