from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from fake_google import FakeGoogle, good_claims
from mental import store
from mental.engine.generate import make_question
from mental.web import auth
from mental.web.app import app
from records import record, records

SETTINGS = auth.Settings(base_url="http://testserver", client_id="test-client", client_secret="test-secret")


@pytest.fixture(autouse=True)
def google(monkeypatch):
    """Every test talks to a fake Google with sign-in set up."""
    fake = FakeGoogle()
    monkeypatch.setattr(auth, "post_form", fake)
    app.dependency_overrides[auth.settings] = lambda: SETTINGS
    yield fake
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def start_sign_in(client):
    """Click 'Sign in with Google'; returns the state Google will send back."""
    response = client.get("/auth/google", follow_redirects=False)
    return parse_qs(urlparse(response.headers["location"]).query)["state"][0]


def finish_sign_in(client, google, state, sub):
    google.codes[f"code-{sub}"] = good_claims(sub)
    return client.get("/auth/callback", params={"code": f"code-{sub}", "state": state}, follow_redirects=False)


def sign_in(client, google, sub="google-me", name="me"):
    response = finish_sign_in(client, google, start_sign_in(client), sub)
    assert response.headers["location"] == "/"
    if name:
        assert client.put("/api/me/name", json={"name": name}).status_code == 200


def player_count():
    conn = store.connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    finally:
        conn.close()


def me(client):
    return client.get("/api/me").json()


def save(client, mode, attempts):
    return client.post("/api/rounds", json={"mode": mode, "attempts": attempts})


def set_cookies(response):
    return [value for key, value in response.headers.multi_items() if key == "set-cookie"]


# --- questions and the page ---------------------------------------------------

def test_questions_for_one_category(client):
    response = client.get("/api/questions", params={"category": "addition", "difficulty": 1, "count": 5})
    assert response.status_code == 200
    questions = response.json()
    assert len(questions) == 5
    assert {q["category"] for q in questions} == {"addition"}
    assert {"id", "seed", "text", "answer", "strategy", "difficulty", "steps"} <= questions[0].keys()


def test_questions_for_a_category_list(client):
    response = client.get("/api/questions", params={"category": "addition,division", "count": 40})
    assert {q["category"] for q in response.json()} <= {"addition", "division"}


def test_unknown_category_is_400(client):
    assert client.get("/api/questions", params={"category": "astrology"}).status_code == 400


def test_difficulty_out_of_range_is_422(client):
    assert client.get("/api/questions", params={"difficulty": 4}).status_code == 422


def test_mixed_difficulty_mixes_levels(client):
    response = client.get("/api/questions", params={"difficulty": "mixed", "count": 200})
    assert response.status_code == 200
    assert {q["difficulty"] for q in response.json()} == {1, 2, 3}


def test_difficulty_that_is_not_a_level_is_422(client):
    assert client.get("/api/questions", params={"difficulty": "hard"}).status_code == 422


def test_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "mental" in response.text


def test_pages_and_answers_are_not_cached(client):
    for path in ["/", "/app.js", "/api/me"]:
        assert client.get(path).headers["cache-control"] == "no-cache", path


def test_the_v1_2_player_routes_are_gone(client):
    assert client.get("/api/players").status_code == 404
    assert client.post("/api/players", json={"name": "me"}).status_code == 405


# --- signing in -----------------------------------------------------------------

def test_sign_in_sends_you_to_google(client):
    response = client.get("/auth/google", follow_redirects=False)
    assert response.status_code == 303
    location = urlparse(response.headers["location"])
    query = {key: values[0] for key, values in parse_qs(location.query).items()}
    assert f"{location.scheme}://{location.netloc}{location.path}" == auth.AUTH_URL
    assert (query["client_id"], query["scope"], query["code_challenge_method"]) == ("test-client", "openid", "S256")
    assert query["redirect_uri"] == "http://testserver/auth/callback"
    [cookie] = set_cookies(response)
    assert cookie.startswith(f"mental_oauth_state={query['state']};")
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie


def test_sign_in_when_not_set_up(client):
    app.dependency_overrides[auth.settings] = lambda: auth.Settings("http://testserver", None, None)
    assert client.get("/auth/google", follow_redirects=False).headers["location"] == "/?signin=unavailable"
    assert me(client) == {"signed_in": False, "name": None, "google": False}


def test_signing_in(client, google):
    assert me(client) == {"signed_in": False, "name": None, "google": True}
    sign_in(client, google, name=None)
    assert me(client) == {"signed_in": True, "name": None, "google": True}
    assert client.put("/api/me/name", json={"name": "Denn"}).json() == {"name": "Denn"}
    assert me(client)["name"] == "Denn"


def test_the_session_cookie_is_httponly_lax_and_lasts_30_days(client, google):
    response = finish_sign_in(client, google, start_sign_in(client), "google-me")
    [session] = [c for c in set_cookies(response) if c.startswith("mental_session=")]
    for part in ["HttpOnly", "SameSite=lax", "Path=/", "Max-Age=2592000"]:
        assert part in session


def test_on_https_cookies_are_secure_and_host_only(google):
    app.dependency_overrides[auth.settings] = lambda: auth.Settings("https://testserver", "test-client", "test-secret")
    client = TestClient(app, base_url="https://testserver")
    response = client.get("/auth/google", follow_redirects=False)
    [state_cookie] = set_cookies(response)
    assert state_cookie.startswith("__Host-mental_oauth_state=") and "Secure" in state_cookie
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    response = finish_sign_in(client, google, state, "google-me")
    assert any(c.startswith("__Host-mental_session=") and "Secure" in c for c in set_cookies(response))
    assert me(client)["signed_in"] is True


def test_the_state_must_match_this_browsers_cookie(google):
    for other in [TestClient(app), TestClient(app, cookies={"mental_oauth_state": "something-else"})]:
        state = start_sign_in(TestClient(app))  # started in one browser (a fresh state each time)...
        response = finish_sign_in(other, google, state, "google-me")  # ...finished in another
        assert response.headers["location"] == "/?signin=failed"
        assert me(other)["signed_in"] is False


def test_a_state_works_once(client, google):
    state = start_sign_in(client)
    assert finish_sign_in(client, google, state, "google-me").headers["location"] == "/"
    again = TestClient(app, cookies={"mental_oauth_state": state})
    assert finish_sign_in(again, google, state, "google-me").headers["location"] == "/?signin=failed"
    assert me(again)["signed_in"] is False


def test_cancelling_at_google(client):
    state = start_sign_in(client)
    response = client.get("/auth/callback", params={"error": "access_denied", "state": state}, follow_redirects=False)
    assert response.headers["location"] == "/?signin=cancelled"
    assert me(client)["signed_in"] is False
    assert player_count() == 0


def test_other_errors_from_google_are_logged(client, caplog):
    state = start_sign_in(client)
    response = client.get("/auth/callback", params={"error": "invalid_request", "state": state}, follow_redirects=False)
    assert response.headers["location"] == "/?signin=cancelled"
    assert "invalid_request" in caplog.text
    caplog.clear()
    client.get("/auth/callback", params={"error": "access_denied", "state": start_sign_in(client)}, follow_redirects=False)
    assert "access_denied" not in caplog.text


def test_a_code_google_refuses(client):
    state = start_sign_in(client)
    response = client.get("/auth/callback", params={"code": "unknown", "state": state}, follow_redirects=False)
    assert response.headers["location"] == "/?signin=failed"
    assert me(client)["signed_in"] is False
    assert player_count() == 0


def test_signing_in_again_ends_the_old_session(client, google):
    sign_in(client, google)
    old = client.cookies.get("mental_session")
    sign_in(client, google, name=None)
    assert client.cookies.get("mental_session") != old
    assert me(client)["signed_in"] is True
    assert me(TestClient(app, cookies={"mental_session": old}))["signed_in"] is False


def test_the_same_google_account_is_the_same_player(client, google):
    sign_in(client, google, sub="google-1", name="me")
    client.post("/auth/signout")
    sign_in(client, google, sub="google-1", name=None)
    assert me(client)["name"] == "me"


def test_signing_out(client, google):
    sign_in(client, google)
    token = client.cookies.get("mental_session")
    assert client.post("/auth/signout").status_code == 204
    assert me(client)["signed_in"] is False
    assert me(TestClient(app, cookies={"mental_session": token}))["signed_in"] is False  # the old cookie is dead too


def test_a_made_up_session_cookie_is_a_guest():
    assert me(TestClient(app, cookies={"mental_session": "made-up"}))["signed_in"] is False


# --- display names --------------------------------------------------------------

def test_naming_needs_a_session(client):
    assert client.put("/api/me/name", json={"name": "me"}).status_code == 401


def test_a_taken_name_is_409(google):
    first, second = TestClient(app), TestClient(app)
    sign_in(first, google, sub="google-1", name="Denn")
    sign_in(second, google, sub="google-2", name=None)
    assert second.put("/api/me/name", json={"name": "DENN"}).status_code == 409


def test_keeping_your_own_name_is_fine(client, google):
    sign_in(client, google, name="me")
    assert client.put("/api/me/name", json={"name": "me"}).status_code == 200


@pytest.mark.parametrize("name", ["", " me", "me ", "a" * 17, "<b>hi</b>", "x'; DROP TABLE players;--"])
def test_bad_names_are_422(client, google, name):
    sign_in(client, google, name=None)
    assert client.put("/api/me/name", json={"name": name}).status_code == 422


def test_unencodable_text_is_422_not_500(client):
    body = b'{"name": "a\\ud800"}'
    response = client.put("/api/me/name", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 422


# --- rounds -----------------------------------------------------------------------

def test_a_guest_round_gets_its_summary_but_is_not_saved(client):
    body = save(client, "test", records(3, wrong=1)).json()
    assert (body["saved"], body["best"]) == (False, None)
    assert body["summary"]["overall"]["score"] == 3
    assert client.get("/api/leaderboard").json() == []


def test_a_round_before_choosing_a_name_is_not_saved(client, google):
    sign_in(client, google, name=None)
    assert save(client, "test", records(2)).json()["saved"] is False
    client.put("/api/me/name", json={"name": "me"})
    assert client.get("/api/me/stats").json()["tests"]["count"] == 0


def test_a_signed_in_round_is_saved(client, google):
    sign_in(client, google)
    body = save(client, "practice", records(3, wrong=1)).json()
    assert (body["saved"], body["best"]) == (True, None)  # practice has no best
    assert body["summary"]["overall"]["skipped"] == 1
    assert client.get("/api/me/stats").json()["by_category"]["addition"]["count"] == 4


def test_rounds_are_saved_for_the_session_not_the_body(google):
    mine, theirs = TestClient(app), TestClient(app)
    sign_in(mine, google, sub="google-1", name="me")
    sign_in(theirs, google, sub="google-2", name="them")
    mine.post("/api/rounds", json={"player_id": 2, "mode": "test", "attempts": records(2)})
    assert mine.get("/api/me/stats").json()["tests"]["count"] == 1
    assert theirs.get("/api/me/stats").json()["tests"]["count"] == 0


def test_the_server_decides_what_is_correct(client, google):
    sign_in(client, google)
    q = make_question("multiplication", 2, 5)
    wrong = record(q, str(q.answer + 1), correct=True)
    assert save(client, "test", [wrong]).json()["summary"]["overall"]["score"] == 0


def test_test_rounds_report_the_best(client, google):
    sign_in(client, google)
    assert save(client, "test", records(4)).json()["best"] == {"previous": None, "best": 4}
    assert save(client, "test", records(6)).json()["best"] == {"previous": 4, "best": 6}
    assert save(client, "test", records(5)).json()["best"] == {"previous": 6, "best": 6}


def test_attempt_that_does_not_match_its_question_is_400(client):
    changed = records(1)
    changed[0]["text"] = "2 + 2"
    assert save(client, "test", changed).status_code == 400


def test_question_id_with_a_huge_seed_is_400(client):
    q = make_question("addition", 1, 5)
    huge = record(q, str(q.answer), question_id=f"addition-1-{10**30}")
    assert save(client, "test", [huge]).status_code == 400


def test_bad_attempt_is_422(client):
    bad = records(1)
    bad[0]["time_ms"] = -5
    assert save(client, "test", bad).status_code == 422


@pytest.mark.parametrize("field, value", [
    ("given", ""), ("given", "-"), ("given", "−465"), ("given", "12345"), ("wrong_tries", ["−4", "-", "99999"]),
])
def test_anything_the_answer_box_allows_is_accepted(client, field, value):
    ok = records(1)
    ok[0][field] = value
    assert save(client, "practice", ok).status_code == 200


@pytest.mark.parametrize("field, value", [
    ("given", "12a"), ("given", "1234567"), ("wrong_tries", ["hello"]),
    ("seed", -1), ("difficulty", 4), ("answer", 100_000),
])
def test_attempt_fields_out_of_shape_are_422(client, field, value):
    bad = records(1)
    bad[0][field] = value
    assert save(client, "test", bad).status_code == 422


def test_too_many_attempts_is_422(client):
    assert save(client, "test", records(1) * 1001).status_code == 422


def test_a_round_cannot_repeat_a_question(client):
    assert save(client, "test", records(1) * 2).status_code == 400


# --- stats and the leaderboard ------------------------------------------------------

def test_stats_need_a_session(client):
    assert client.get("/api/me/stats").status_code == 401


def test_stats_for_the_signed_in_player(client, google):
    sign_in(client, google)
    save(client, "test", records(2, wrong=1))
    save(client, "practice", records(3))
    stats = client.get("/api/me/stats").json()
    assert (stats["tests"]["count"], stats["tests"]["best"]) == (1, 2)
    assert stats["by_category"]["addition"]["count"] == 6
    assert stats["by_category"]["addition"]["score"] == 5


def test_leaderboard_marks_your_row_and_sends_no_ids(google):
    mine, yours = TestClient(app), TestClient(app)
    sign_in(mine, google, sub="google-1", name="me")
    sign_in(yours, google, sub="google-2", name="you")
    save(mine, "test", records(2))
    save(yours, "test", records(3))
    assert mine.get("/api/leaderboard").json() == [
        {"name": "you", "best": 3, "me": False},
        {"name": "me", "best": 2, "me": True},
    ]
    assert not any(row["me"] for row in TestClient(app).get("/api/leaderboard").json())  # a guest is nobody
