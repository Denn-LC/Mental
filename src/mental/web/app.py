from dataclasses import asdict
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from mental.engine.generate import CATEGORIES, make_questions
from mental.engine.summary import summarise

app = FastAPI(title="mental")


@app.get("/api/questions")
def get_questions(
    category: str = "mixed",  # "mixed", one category, or a comma-separated list
    difficulty: int = Query(1, ge=1, le=3),
    count: int = Query(20, ge=1, le=200),
):
    categories = CATEGORIES if category == "mixed" else category.split(",")
    unknown = [c for c in categories if c not in CATEGORIES]
    if unknown:
        raise HTTPException(400, f"unknown category: {', '.join(unknown)}")
    try:
        questions = make_questions(categories, difficulty, count)
    except ValueError as error:
        raise HTTPException(400, str(error))
    return [asdict(q) for q in questions]


class Attempt(BaseModel):
    """One attempt record, as built by app.js. Checked here because it comes from the browser."""

    question_id: str
    seed: int
    text: str
    category: str
    strategy: str
    difficulty: int
    answer: int
    given: str
    correct: bool
    skipped: bool
    wrong_tries: list[str]
    hints_used: int = Field(ge=0, le=3)
    time_ms: int = Field(ge=0)
    mode: Literal["free", "test"]


@app.post("/api/summary")
def post_summary(attempts: list[Attempt]):
    if len(attempts) > 1000:
        raise HTTPException(413, "too many attempts")
    return summarise([a.model_dump() for a in attempts])


# Mounted last so it doesn't swallow the /api routes.
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
