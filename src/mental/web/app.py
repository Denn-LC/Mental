import logging
import secrets
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from mental import store
from mental.engine.check import checked
from mental.engine.generate import CATEGORIES, make_questions
from mental.engine.summary import group_stats, summarise
from mental.web import auth

app = FastAPI(title="mental")
log = logging.getLogger("mental.auth")

# 1-16 letters, digits, spaces, _ . - and no space at either end (app.js uses the same rule)
NAME = r"^[A-Za-z0-9_.-]([A-Za-z0-9 _.-]{0,14}[A-Za-z0-9_.-])?$"
SESSION_COOKIE = "mental_session"
STATE_COOKIE = "mental_oauth_state"


@app.exception_handler(RequestValidationError)
async def invalid_body(request, error):
    """Report only where and why; the default reply echoes the input, and a lone surrogate in it can't be encoded (500)."""
    return JSONResponse(
        {"detail": [{"loc": e["loc"], "msg": e["msg"]} for e in error.errors()]}, status_code=422
    )


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
Settings = Annotated[auth.Settings, Depends(auth.settings)]
Typed = Annotated[str, Field(pattern=r"^[-−]?[0-9]{0,5}$")]  # what the answer box allows: "", "-", "-465", "−465"


# --- cookies and who is signed in ---------------------------------------------------

def cookie_name(settings, name):
    """On https a cookie gets the __Host- prefix: only this exact site, over https, can set it."""
    return f"__Host-{name}" if settings.secure else name


def set_cookie(response, settings, name, value, max_age):
    response.set_cookie(cookie_name(settings, name), value, max_age=max_age, path="/",
                        secure=settings.secure, httponly=True, samesite="lax")


def clear_cookie(response, settings, name):
    response.delete_cookie(cookie_name(settings, name), path="/", secure=settings.secure, httponly=True, samesite="lax")


def signed_in(request: Request, conn: Database, settings: Settings):
    """The player ({id, name}) this request's session belongs to, or None for a guest."""
    return store.session_player(conn, request.cookies.get(cookie_name(settings, SESSION_COOKIE), ""))


Player = Annotated[dict | None, Depends(signed_in)]


# --- questions ------------------------------------------------------------------------

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


# --- signing in with Google -------------------------------------------------------------

@app.get("/auth/google")
def sign_in(conn: Database, settings: Settings):
    """Send the browser to Google's account chooser."""
    if not settings.enabled:
        return RedirectResponse("/?signin=unavailable", status_code=303)
    state, verifier = auth.new_state(), auth.new_verifier()
    store.save_oauth_state(conn, state, verifier)
    response = RedirectResponse(auth.sign_in_url(settings, state, verifier), status_code=303)
    set_cookie(response, settings, STATE_COOKIE, state, max_age=store.STATE_MINUTES * 60)
    return response


@app.get("/auth/callback")
def sign_in_callback(request: Request, conn: Database, settings: Settings,
                     code: str = "", state: str = "", error: str = ""):
    """Google sends the browser back here: sign in, or go home saying what went wrong."""
    expected = request.cookies.get(cookie_name(settings, STATE_COOKIE), "")
    verifier = store.take_oauth_state(conn, state) if state else None  # a state works once, whatever happens next
    if error:
        if error != "access_denied":
            log.warning("Google sign-in came back with error %r", error[:100])
        return back_home(settings, "cancelled")
    # the state must be one we made, unused, unexpired, and started in this same browser
    if not (settings.enabled and code and verifier and secrets.compare_digest(state.encode(), expected.encode())):
        log.warning("Google sign-in refused: state missing, used, expired or from another browser")
        return back_home(settings, "failed")
    try:
        sub = auth.google_account(settings, code, verifier)
    except auth.SignInFailed as failure:
        log.warning("Google sign-in failed: %s", failure)
        return back_home(settings, "failed")
    player = store.player_for_google(conn, sub)
    store.end_session(conn, request.cookies.get(cookie_name(settings, SESSION_COOKIE)))  # not left valid after a new sign-in
    response = back_home(settings)
    set_cookie(response, settings, SESSION_COOKIE, store.create_session(conn, player["id"]),
               max_age=store.SESSION_DAYS * 24 * 60 * 60)
    return response


def back_home(settings, outcome=None):
    response = RedirectResponse(f"/?signin={outcome}" if outcome else "/", status_code=303)
    clear_cookie(response, settings, STATE_COOKIE)
    return response


@app.post("/auth/signout")
def sign_out(request: Request, conn: Database, settings: Settings):
    token = request.cookies.get(cookie_name(settings, SESSION_COOKIE))
    if token:
        store.end_session(conn, token)
    response = Response(status_code=204)
    clear_cookie(response, settings, SESSION_COOKIE)
    return response


# --- you ------------------------------------------------------------------------------------

class NewName(BaseModel):
    name: str = Field(pattern=NAME)


@app.get("/api/me")
def get_me(player: Player, settings: Settings):
    return {"signed_in": player is not None, "name": player["name"] if player else None, "google": settings.enabled}


@app.put("/api/me/name")
def put_name(body: NewName, player: Player, conn: Database):
    if player is None:
        raise HTTPException(401, "sign in first")
    try:
        store.set_name(conn, player["id"], body.name)
    except store.NameTaken:
        raise HTTPException(409, "that name is taken")
    return {"name": body.name}


# --- rounds, stats and the leaderboard ----------------------------------------------------

class Attempt(BaseModel):
    """One attempt record, as built by app.js. Its question fields and `correct` are re-checked."""

    question_id: str = Field(max_length=64)
    seed: int = Field(ge=0, lt=2**32)
    text: str = Field(max_length=64)
    category: str = Field(max_length=32)
    strategy: str = Field(max_length=32)
    difficulty: int = Field(ge=1, le=3)
    answer: int = Field(ge=-99_999, le=99_999)
    given: Typed
    correct: bool
    skipped: bool
    wrong_tries: list[Typed] = Field(max_length=1000)
    gave_up: bool
    time_ms: int = Field(ge=0, le=10**9)
    mode: Literal["practice", "test"]


class Round(BaseModel):
    mode: Literal["practice", "test"]
    attempts: list[Attempt] = Field(max_length=1000)


@app.post("/api/rounds")
def post_round(body: Round, player: Player, conn: Database):
    """Summarise a finished test or practice session; save it when a named player is signed in."""
    ids = [a.question_id for a in body.attempts]
    if len(set(ids)) < len(ids):
        raise HTTPException(400, "a question appears twice in this round")
    try:
        attempts = [checked(a.model_dump()) for a in body.attempts]
    except ValueError as error:
        raise HTTPException(400, str(error))
    summary = summarise(attempts)
    if player is None or player["name"] is None:
        return {"summary": summary, "best": None, "saved": False}  # guests get the summary only
    previous = store.best_score(conn, player["id"]) if body.mode == "test" else None
    store.save_round(conn, player["id"], body.mode, attempts)
    best = None
    if body.mode == "test":
        best = {"previous": previous, "best": max(summary["overall"]["score"], previous or 0)}
    return {"summary": summary, "best": best, "saved": True}


@app.get("/api/me/stats")
def get_stats(player: Player, conn: Database):
    if player is None:
        raise HTTPException(401, "sign in to see your stats")
    return {
        "tests": store.history(conn, player["id"]),
        "by_category": group_stats(store.player_attempts(conn, player["id"]), "category"),
    }


@app.get("/api/leaderboard")
def get_leaderboard(player: Player, conn: Database):
    me = player["id"] if player else None
    return [{"name": row["name"], "best": row["best"], "me": row["id"] == me} for row in store.leaderboard(conn)]


# Mounted last so it doesn't swallow the /api and /auth routes.
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
