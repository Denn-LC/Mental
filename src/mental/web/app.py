import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi import Path as InPath
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from mental import store
from mental.engine.check import checked
from mental.engine.generate import CATEGORIES, make_questions
from mental.engine.summary import group_stats, summarise

app = FastAPI(title="mental")

# 1-16 letters, digits, spaces, _ . - and no space at either end (app.js uses the same rule)
NAME = r"^[A-Za-z0-9_.-]([A-Za-z0-9 _.-]{0,14}[A-Za-z0-9_.-])?$"
MAX_ID = 2**63 - 1  # the biggest integer SQLite stores; anything bigger can't be a real id


@app.middleware("http")
async def no_cache(request, call_next):
    """A normal reload must check for a newer page or script instead of reusing an old copy."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache"
    return response


def database():
    conn = store.connect()
    try:
        yield conn
    finally:
        conn.close()


Database = Annotated[sqlite3.Connection, Depends(database)]
PlayerId = Annotated[int, Field(ge=1, le=MAX_ID)]
Short = Annotated[str, Field(max_length=16)]


@app.get("/api/questions")
def get_questions(
    category: str = "mixed",  # "mixed", one category, or a comma-separated list
    difficulty: Literal["1", "2", "3", "mixed"] = "1",  # "mixed": each question gets a random level
    count: int = Query(20, ge=1, le=200),
):
    categories = CATEGORIES if category == "mixed" else category.split(",")
    unknown = [c for c in categories if c not in CATEGORIES]
    if unknown:
        raise HTTPException(400, f"unknown category: {', '.join(unknown)}")
    try:
        levels = [1, 2, 3] if difficulty == "mixed" else [int(difficulty)]
        questions = make_questions(categories, levels, count)
    except ValueError as error:
        raise HTTPException(400, str(error))
    return [asdict(q) for q in questions]


class NewPlayer(BaseModel):
    name: str = Field(pattern=NAME)


class Attempt(BaseModel):
    """One attempt record, as built by app.js. Its question fields and `correct` are re-checked."""

    question_id: str = Field(max_length=64)
    seed: int
    text: str = Field(max_length=64)
    category: str = Field(max_length=32)
    strategy: str = Field(max_length=32)
    difficulty: int
    answer: int
    given: Short
    correct: bool
    skipped: bool
    wrong_tries: list[Short] = Field(max_length=1000)
    gave_up: bool
    time_ms: int = Field(ge=0, le=10**9)
    mode: Literal["practice", "test"]


class Round(BaseModel):
    player_id: PlayerId
    mode: Literal["practice", "test"]
    attempts: list[Attempt] = Field(max_length=1000)


@app.get("/api/players")
def get_players(conn: Database):
    return store.players(conn)


@app.post("/api/players")
def post_player(player: NewPlayer, conn: Database):
    try:
        return store.add_player(conn, player.name)
    except store.NameTaken:
        raise HTTPException(409, "that name is taken")


@app.post("/api/rounds")
def post_round(body: Round, conn: Database):
    """Save a finished test or practice session; return its summary and, for a test, the best."""
    if not store.player_exists(conn, body.player_id):
        raise HTTPException(404, "unknown player")
    try:
        attempts = [checked(a.model_dump()) for a in body.attempts]
    except ValueError as error:
        raise HTTPException(400, str(error))
    previous = store.best_score(conn, body.player_id) if body.mode == "test" else None
    store.save_round(conn, body.player_id, body.mode, attempts)
    summary = summarise(attempts)
    best = None
    if body.mode == "test":
        best = {"previous": previous, "best": max(summary["overall"]["score"], previous or 0)}
    return {"summary": summary, "best": best}


@app.get("/api/players/{player_id}/stats")
def get_stats(player_id: Annotated[int, InPath(ge=1, le=MAX_ID)], conn: Database):
    if not store.player_exists(conn, player_id):
        raise HTTPException(404, "unknown player")
    return {
        "tests": store.history(conn, player_id),
        "by_category": group_stats(store.player_attempts(conn, player_id), "category"),
    }


@app.get("/api/leaderboard")
def get_leaderboard(conn: Database):
    return store.leaderboard(conn)


# Mounted last so it doesn't swallow the /api routes.
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
