from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from mental.engine.generate import CATEGORIES, make_questions

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


# Mounted last so it doesn't swallow the /api routes.
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
