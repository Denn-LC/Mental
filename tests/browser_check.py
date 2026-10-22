"""Drive the page in a headless browser and check the keyboard flows, saving and race fixes.

Not part of `pytest` (it needs a running server and a browser). The server gets a database of its
own and made-up Google settings (the check never talks to Google), and the check gets the same
database so it can sign in by making a session in it:

    export MENTAL_DB=$(mktemp -d)/check.db MENTAL_BASE_URL=http://127.0.0.1:8765
    MENTAL_GOOGLE_CLIENT_ID=check-client MENTAL_GOOGLE_CLIENT_SECRET=check-secret \\
        uv run uvicorn mental.web.app:app --port 8765 &
    uv run --with playwright python tests/browser_check.py http://127.0.0.1:8765/

Set CHROMIUM=/path/to/chrome to use a browser Playwright didn't install itself.
"""
import json
import os
import random
import sys
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

from mental import store

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765/"
EXE = os.environ.get("CHROMIUM")
NAME = f"check{random.randint(1000, 9999)}"  # a new player every run
if not os.environ.get("MENTAL_DB"):
    sys.exit("set MENTAL_DB to the server's database first (see the docstring)")


def sign_in(page, sub, name=None):
    """Sign in as a Google account without Google: make its session in the server's database."""
    conn = store.connect()
    player = store.player_for_google(conn, sub)
    if name:
        store.set_name(conn, player["id"], name)
    token = store.create_session(conn, player["id"])
    conn.close()
    page.context.add_cookies([{"name": "mental_session", "value": token, "url": URL}])

results, errors = [], []


def check(name, ok):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name)


def delay(page, path, ms):
    """Make the page's own fetches to path slow, without blocking key presses."""
    page.evaluate("""([path, ms]) => { const real = window.fetch;
      window.fetch = (url, opts) => String(url).includes(path)
        ? new Promise((ok) => setTimeout(ok, ms)).then(() => real(url, opts)) : real(url, opts); }""", [path, ms])


def fail(page, path, times=1000):
    """Make the next `times` fetches to path fail as if the server were down."""
    page.evaluate("""([path, times]) => { const real = window.fetch; let n = 0;
      window.fetch = (url, opts) => (String(url).includes(path) && n++ < times)
        ? Promise.reject(new Error("offline")) : real(url, opts); }""", [path, times])


def centre_y(page, selector):
    """How far the middle of an element is from the middle of the window, as a share of its height."""
    return page.evaluate(f"""(() => {{ const r = document.querySelector('{selector}').getBoundingClientRect();
        return Math.abs(r.top + r.height / 2 - innerHeight / 2) / innerHeight; }})()""")


def visible(page, element_id):
    return page.evaluate(f"getComputedStyle(document.getElementById('{element_id}')).display !== 'none'")


def waited(page, condition, timeout=10000):
    """True once the page's JS condition holds; False (a FAIL, not a crash) if it never does."""
    try:
        page.wait_for_function(condition, timeout=timeout)
        return True
    except Exception:
        return False


# Builds n attempt records for real, distinct questions straight into the page (as if n questions
# were answered right) and returns how many bytes they make as a /api/rounds body.
FAKE_SESSION = """async (n) => {
  const batches = await Promise.all([1, 2, 3].map(() => getJSON('/api/questions?difficulty=mixed&count=200')));
  const questions = batches.flat().slice(0, n);
  for (const q of questions) state.seen[q.id] = q;
  state.attempts = questions.map((q) => ({ question_id: q.id, seed: q.seed, text: q.text,
    category: q.category, strategy: q.strategy, difficulty: q.difficulty, answer: q.answer,
    given: String(q.answer), correct: true, skipped: false, wrong_tries: [], gave_up: false,
    time_ms: 1000, mode: 'practice' }));
  return JSON.stringify({ mode: 'practice', attempts: state.attempts }).length;
}"""


def saved_count(page):
    """How many attempts the server has saved for the signed-in account."""
    return page.evaluate("""fetch('/api/me/stats').then((r) => r.json())
        .then((s) => Object.values(s.by_category).reduce((n, c) => n + c.count, 0))""")


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=EXE) if EXE else p.chromium.launch()
    page = browser.new_page(viewport={"width": 900, "height": 900})
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route("https://accounts.google.com/**", lambda route: route.abort())  # a guard: no run can reach Google
    page.goto(URL)
    answer = lambda: page.evaluate("state.current.answer")
    playing = lambda: page.wait_for_function("state.current && !state.countingDown", timeout=10000)
    running = lambda: page.wait_for_function("state.testEndsAt > 0", timeout=10000)
    focused = lambda: page.evaluate("(({ dataset, id, value, textContent }) => dataset.mode || id || value || textContent)(document.activeElement)")
    home = lambda: page.wait_for_selector("#home:not([hidden])")

    # welcome and guest play
    page.wait_for_selector("#welcome:not([hidden])")
    check("a new visitor gets Welcome: sign in with Google or play as guest",
          visible(page, "welcome-signin") and visible(page, "guest-choice") and focused() == "welcome-signin")
    check("Welcome says guest games aren't saved, where it can be seen",
          page.get_by_text("aren't saved").first.is_visible())
    page.click("#guest-choice")
    home()
    check("Play as guest goes home as a guest, with Sign in and no Account",
          page.text_content("#playing-as") == "playing as guest · nothing is saved"
          and visible(page, "home-signin") and not visible(page, "account-choice"))
    page.click("[data-mode=practice]")
    page.click("#play")
    playing()
    page.keyboard.press("Tab")
    page.click("#quit")
    page.wait_for_selector("#results:not([hidden])")
    check("a guest's practice summary says it isn't saved", "not saved · sign in" in page.text_content("#results"))
    page.keyboard.press("Escape")
    page.click("[data-mode=test]")
    running()
    page.evaluate("state.testEndsAt = performance.now()")
    page.wait_for_selector("#results:not([hidden])")
    check("a guest's test results have no best line",
          "score" in page.text_content("#results") and "best" not in page.text_content("#results")
          and "not saved · sign in" in page.text_content("#results"))
    page.keyboard.press("Escape")
    page.click("#my-stats-choice")
    check("a guest's My stats asks them to sign in",
          visible(page, "stats-signin") and not visible(page, "my-stats-body") and focused() == "stats-signin")
    page.keyboard.press("Escape")
    page.click("#leaderboard-choice")
    check("a guest sees the leaderboard with a sign-in prompt", visible(page, "board-signin") and visible(page, "leaderboard-list"))
    page.keyboard.press("Escape")

    # signing in
    # Chromium here doesn't route redirected requests, so the check stops at the app's own redirect:
    # it reads where /auth/google points and answers with a stub page, so Google is never contacted.
    sent_to = []

    def stub_google(route):
        reply = route.fetch(max_redirects=0)
        sent_to.append(reply.headers.get("location", ""))
        route.fulfill(body="Google's account chooser")

    page.route("**/auth/google", stub_google)
    page.click("#home-signin")
    page.wait_for_function("document.body.textContent.includes(\"Google's account chooser\")")
    page.unroute("**/auth/google")
    check("Sign in with Google redirects to Google's own address", sent_to[0].startswith("https://accounts.google.com/"))
    query = {key: values[0] for key, values in parse_qs(urlparse(sent_to[0]).query).items()}
    check("...with this app's client, PKCE and only the openid scope",
          query.get("client_id") == "check-client" and query.get("scope") == "openid"
          and query.get("code_challenge_method") == "S256" and query.get("redirect_uri") == URL.rstrip("/") + "/auth/callback")
    page.goto(URL + "?signin=cancelled")
    page.wait_for_selector("#welcome:not([hidden])")
    check("coming back cancelled says so on Welcome, and the address is cleaned up",
          page.text_content("#signin-message") == "Sign-in cancelled." and page.url == URL)
    sign_in(page, f"google-{NAME}")
    page.goto(URL)
    page.wait_for_selector("#account:not([hidden])")
    check("a first sign-in asks for a display name, with no Back",
          page.text_content("#account-title") == "pick a display name" and not visible(page, "account-back")
          and focused() == "name-box")
    page.keyboard.press("Escape")
    page.wait_for_selector("#welcome:not([hidden])")
    check("Esc on the first name screen signs out", page.evaluate("fetch('/api/me').then((r) => r.json()).then((m) => !m.signed_in)"))
    sign_in(page, f"google-{NAME}")
    page.goto(URL)
    page.wait_for_selector("#account:not([hidden])")
    page.keyboard.type("no <tags>")
    page.keyboard.press("Enter")
    check("a bad name gets a message and stays", "1-16 letters" in page.text_content("#name-error") and visible(page, "account"))
    page.fill("#name-box", "")
    page.keyboard.type(NAME)
    page.keyboard.press("ArrowLeft")
    check("left/right in the name box move the caret, not the highlight", focused() == "name-box")
    page.keyboard.press("Enter")
    home()
    check("a display name goes home playing as it, Practice highlighted, Account instead of Sign in",
          page.text_content("#playing-as") == f"playing as {NAME}" and focused() == "practice"
          and visible(page, "account-choice") and not visible(page, "home-signin"))
    taken = f"taken{NAME[5:]}"
    other = store.connect()
    store.set_name(other, store.player_for_google(other, f"google-other-{NAME}")["id"], taken)  # someone else holds this name
    other.close()
    page.click("#account-choice")
    check("Account shows your name in the box, with Back and Sign out",
          page.input_value("#name-box") == NAME and visible(page, "account-back") and visible(page, "sign-out"))
    page.fill("#name-box", taken.upper())
    page.press("#name-box", "Enter")
    page.wait_for_function("$('name-error').textContent !== ''")
    check("a taken name (in any case) gets a message", "taken" in page.text_content("#name-error"))
    renamed = f"{NAME}b"
    page.fill("#name-box", renamed)
    page.press("#name-box", "Enter")
    home()
    check("a successful rename goes home, Account highlighted, showing the new name",
          page.text_content("#playing-as") == f"playing as {renamed}" and focused() == "account-choice")
    page.click("#account-choice")
    page.fill("#name-box", NAME)
    page.press("#name-box", "Enter")
    home()
    page.click("#account-choice")
    page.keyboard.press("Escape")
    check("Esc on Account goes home, Account highlighted", visible(page, "home") and focused() == "account-choice")
    page.focus("[data-mode=practice]")

    # home screen
    check("the title is near the top (not touching it), centred",
          page.evaluate("(() => { const r = document.querySelector('h1').getBoundingClientRect(); return r.top > 40 && r.top < 100 && Math.abs(r.left + r.width / 2 - innerWidth / 2) < 5; })()"))
    check("the home menu sits in the middle of the screen", centre_y(page, "#home") < 0.1)
    page.keyboard.press("ArrowDown")
    check("arrow down highlights Test Yourself", focused() == "test")
    page.keyboard.press("ArrowRight")
    check("arrows stop at the side instead of wrapping", focused() == "test")
    page.keyboard.press("ArrowUp")
    page.keyboard.press("ArrowUp")
    check("arrow up goes back up and stops at the top", focused() == "practice")
    test_box = page.locator("[data-mode=test]").bounding_box()
    page.hover("[data-mode=test]")
    check("the highlight follows the mouse", focused() == "test")
    page.keyboard.press("ArrowUp")
    page.keyboard.down("Enter")
    check("Enter on Practice opens its options, Play highlighted", visible(page, "options") and focused() == "play")
    page.keyboard.down("Enter")  # the key is still held: this one is a repeat
    page.keyboard.up("Enter")
    check("holding Enter doesn't run on into Play", visible(page, "options") and focused() == "play")
    check("the options sit in the middle of the screen", centre_y(page, "#options fieldset:last-of-type") < 0.1)

    # practice options: the arrows move the way they point (topics are a 3 x 2 grid at this width)
    page.keyboard.press("ArrowUp")
    check("up from Play reaches a level", focused() in ("1", "2", "3", "mixed"))
    page.keyboard.press("ArrowUp")
    check("up again reaches the bottom row of topics", focused() in ("division", "percentage", "relationship"))
    page.focus("input[value=addition]")
    page.keyboard.press("ArrowRight")
    check("right moves along the row", focused() == "subtraction")
    page.keyboard.press("ArrowDown")
    check("down moves down the column", focused() == "percentage")
    page.keyboard.press("ArrowLeft")
    check("left moves back along the row", focused() == "division")
    page.focus("input[value=addition]")
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("ArrowUp")
    check("left/up at the edge stay put", focused() == "addition")
    for topic in ["addition", "subtraction", "multiplication", "division", "percentage", "relationship"]:
        page.focus(f"input[value={topic}]")
        page.keyboard.press("Enter")
    check("Enter unticks topics", page.evaluate("document.querySelectorAll('input[name=topic]:checked').length") == 0)
    page.focus("input[name=level][value='2']")
    page.keyboard.press("Space")
    check("Space picks level 2", page.evaluate("document.querySelector('input[name=level]:checked').value") == "2")
    page.keyboard.press("ArrowDown")
    check("down from the levels reaches Play", focused() == "play")
    page.keyboard.press("Enter")
    check("Play with no topics -> message, stays on options", "Tick at least one" in page.text_content("#menu-error") and visible(page, "options"))
    page.click("text=multiplication")
    page.keyboard.press("Escape")
    check("Esc goes from options back to home", visible(page, "home"))
    page.keyboard.press("Enter")
    page.click("#play")
    check("Play starts a 3-2-1 countdown", page.text_content("#question") == "3" and page.evaluate("state.countingDown"))
    check("no answer box or buttons during the countdown",
          not visible(page, "answer") and not visible(page, "practice-buttons") and not visible(page, "test-buttons"))
    countdown_at = centre_y(page, "#question")
    check("the countdown number is big and in the middle of the screen",
          page.evaluate("parseFloat(getComputedStyle($('question')).fontSize) >= 64") and countdown_at < 0.06)
    page.keyboard.type("5")
    page.keyboard.press("Enter")
    check("Enter during the countdown does nothing", page.evaluate("state.countingDown && state.attempts.length === 0"))
    playing()
    check("then a question, with the chosen settings", page.text_content("#settings") == "practice · multiplication · level 2" and page.input_value("#answer") == "")
    check("the answer box and Practice's buttons appear with the question",
          visible(page, "answer") and visible(page, "practice-buttons") and not visible(page, "test-buttons"))
    check("the answer box appears where the countdown was", centre_y(page, "#answer") < 0.06)
    page.keyboard.type("1234567")
    check("the answer box takes at most 5 digits", page.input_value("#answer") == "12345")
    page.keyboard.press("Control+a")
    page.keyboard.type("-9876543")
    check("...plus a leading minus", page.input_value("#answer") == "-98765")
    page.keyboard.press("Control+a")
    page.keyboard.press("Backspace")
    check("home and options are hidden during play", not visible(page, "home") and not visible(page, "options"))
    check("all text uses the pixel font", page.evaluate("[...document.querySelectorAll('body *')].every((el) => getComputedStyle(el).fontFamily.includes('Press Start 2P'))"))

    # practice
    page.keyboard.type(str(answer() * 5))
    page.keyboard.press("Enter")
    way = page.text_content("#feedback")
    page.keyboard.press("Control+a")
    page.keyboard.type(str(answer() + 1))
    page.keyboard.press("Enter")
    close = page.text_content("#feedback")
    check(f"practice: far answer gets a 'way off' line ({way!r}), off-by-one a close one ({close!r})",
          way in ["are you even trying?", "jesus.", "that's not even close", "...what?", "bold guess"]
          and close in ["almost!", "so close", "nearly there", "off by a hair"])
    page.keyboard.press("Tab")
    check("Tab gives up: answer and steps shown, button says Next, give-up disabled",
          page.text_content("#feedback").startswith("the answer is") and page.eval_on_selector_all("#steps li", "e => e.length") > 0
          and page.text_content("#submit") == "Next" and page.evaluate("$('give-up').disabled"))
    check("give-up recorded as gave_up, not correct, streak reset",
          page.evaluate("state.attempts.at(-1).gave_up && !state.attempts.at(-1).correct && state.streak === 0"))
    q = page.evaluate("state.current.id")
    page.keyboard.press("Enter")
    page.wait_for_timeout(100)
    check("Enter after giving up -> next question", q != page.evaluate("state.current.id") and not page.evaluate("state.solved"))
    page.click("#give-up")
    check("Give up button works and focus returns to the box", page.text_content("#submit") == "Next" and focused() == "answer")
    page.click("#submit")
    page.wait_for_timeout(100)
    page.fill("#answer", str(answer()))
    page.click("#submit")
    check("Enter button submits a right answer", page.text_content("#feedback").startswith("correct"))
    attempts = page.evaluate("state.attempts.length")
    page.keyboard.press("Tab")
    check("Tab after answering does nothing more", page.evaluate("state.solved") and page.evaluate("state.attempts.length") == attempts)
    for width in [900, 400]:
        page.set_viewport_size({"width": width, "height": 800})
        page.evaluate("showQuestion({id:'x', seed:1, text:'98 × 30 = 49 × ?', answer:60, category:'relationship', strategy:'double_halve', difficulty:2, steps:['98 ÷ 2 = 49', '30 × 2 = 60']})")
        check(f"longest question stays on one line at {width}px",
              page.evaluate("$('question').getClientRects().length === 1 && $('question').offsetHeight < 80 && document.documentElement.scrollWidth <= innerWidth"))
    page.set_viewport_size({"width": 900, "height": 900})

    # quitting practice
    page.evaluate("nextQuestion()")  # a real question again after the made-up one
    page.keyboard.press("Tab")  # give it up, so it is saved too
    before = saved_count(page)
    done = page.evaluate("state.attempts.length")
    page.evaluate("state.queue = []")
    delay(page, "/api/questions", 600)
    page.keyboard.press("Enter")  # next question: a slow refill starts...
    page.keyboard.press("Escape")  # ...and Esc quits before it lands
    page.wait_for_selector("#results:not([hidden])")
    summary = page.text_content("#results")
    check("Esc quits practice and shows its summary", "practice done" in summary and f"{done} questions" in summary)
    check("the summary has times per topic and the slowest questions", "avg" in summary and "slowest" in summary)
    page.keyboard.press("Enter")
    page.wait_for_timeout(200)
    check("Enter right after quitting keeps the summary", visible(page, "results"))
    page.wait_for_timeout(900)  # the slow refill lands in here
    check("a refill landing after quitting shows nothing",
          page.text_content("#question") == "done!" and page.evaluate("state.current === null") and visible(page, "results"))
    check("the session was saved once", saved_count(page) == before + done)
    page.keyboard.press("Enter")
    check("Enter a second later practises again with the same settings",
          page.text_content("#question") == "3" and page.text_content("#settings") == "practice · multiplication · level 2")
    playing()
    page.mouse.move(test_box["x"] + 20, test_box["y"] + 20)  # rest the pointer where Test Yourself will appear
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    check("Esc with nothing answered goes straight home, Practice highlighted even under a resting pointer",
          visible(page, "home") and focused() == "practice")
    page.keyboard.press("Enter")
    page.keyboard.press("Enter")
    playing()
    page.keyboard.press("Tab")
    page.click("#quit")
    page.wait_for_selector("#results:not([hidden])")
    check("the Quit button quits too", "1 question ·" in page.text_content("#results"))
    page.keyboard.press("Escape")
    check("Esc on the summary goes home", visible(page, "home"))
    page.keyboard.press("Enter")
    page.keyboard.press("Enter")
    playing()
    before = saved_count(page)
    for _ in range(2):
        page.keyboard.press("Tab")
        page.keyboard.press("Enter")
        playing()
    page.reload()
    home()
    page.wait_for_timeout(300)
    check("reloading mid-practice still saves what was finished", saved_count(page) == before + 2)
    check("a reload keeps you signed in", page.text_content("#playing-as") == f"playing as {NAME}")
    page.keyboard.press("Enter")
    page.keyboard.press("Enter")
    playing()
    before = saved_count(page)
    size = page.evaluate(FAKE_SESSION, 400)
    page.click("#quit")
    check(f"quitting a long practice session ({size // 1000}KB, over the 64KB keepalive cap) saves all of it",
          size > 64000 and waited(page, "!$('results').hidden && $('results').textContent.includes('400 questions')")
          and saved_count(page) == before + 400)
    page.keyboard.press("Escape")
    page.keyboard.press("Enter")
    page.keyboard.press("Enter")
    playing()
    before = saved_count(page)
    page.evaluate(FAKE_SESSION, 400)
    page.reload()
    home()
    page.wait_for_timeout(500)
    after = saved_count(page)
    check(f"closing the tab on a long session still saves its first pieces ({after - before} of 400)",
          after - before >= 100 and (after - before) % 100 == 0)
    page.context.add_cookies([{"name": "mental_session", "value": "made-up", "url": URL}])

    page.reload()
    page.wait_for_selector("#welcome:not([hidden])")
    check("an unknown session cookie shows Welcome", visible(page, "welcome"))
    sign_in(page, f"google-{NAME}")
    page.goto(URL)
    home()
    check("signing in again lands home as the same player", page.text_content("#playing-as") == f"playing as {NAME}")

    # test mode
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    check("Test Yourself goes straight to the countdown (no options)", visible(page, "game") and page.text_content("#question") == "3")
    running()
    check("test mode shows a Skip button, not Practice's buttons", visible(page, "test-buttons") and not visible(page, "practice-buttons"))
    check("timer starts at 2:00 after the countdown", page.text_content("#timer") in ("2:00", "1:59"))
    check("test mixes all topics and levels",
          page.evaluate("new Set(state.queue.map((q) => q.difficulty)).size === 3 && new Set(state.queue.map((q) => q.category)).size === 6"))
    page.keyboard.type(str(answer() * 5))
    page.keyboard.press("Enter")
    check("a wrong answer shows nothing in test mode, but is recorded",
          page.text_content("#feedback") == "" and page.evaluate("state.attempt.wrong_tries.length") == 1)
    page.keyboard.press("Enter")
    check("Enter again on the same wrong value records it once", page.evaluate("state.attempt.wrong_tries.length") == 1)
    page.keyboard.press("Control+a")
    q = page.evaluate("state.current.id")
    page.keyboard.type(str(answer()))
    page.wait_for_timeout(50)
    check("right answer auto-advances", q != page.evaluate("state.current.id"))
    page.keyboard.press("Tab")
    page.wait_for_timeout(50)
    check("Tab skips in test mode", page.evaluate("state.attempts.at(-1).skipped"))
    q = page.evaluate("state.current.id")
    page.click("#skip")
    page.wait_for_timeout(50)
    check("the Skip button skips too, and focus returns to the box",
          page.evaluate("state.attempts.at(-1).skipped") and q != page.evaluate("state.current.id") and focused() == "answer")
    page.evaluate("state.queue = []")
    delay(page, "/api/questions", 600)
    before = page.evaluate("state.attempts.length")
    for _ in range(3):
        page.keyboard.press("Tab")
    check("no answer box or old question while the queue refills",
          not visible(page, "answer") and not visible(page, "test-buttons") and page.text_content("#question") == "")
    page.wait_for_timeout(900)
    check("Tab held while the queue refills records the question once", page.evaluate("state.attempts.length") == before + 1)
    page.evaluate("state.queue = []")
    page.keyboard.press("Tab")  # starts a slow refill...
    page.evaluate("state.testEndsAt = performance.now()")  # ...and the time runs out before it lands
    page.wait_for_selector("#results:not([hidden])")
    check("results appear after time", "score" in page.text_content("#results"))
    check("a first test says so", "first test · best" in page.text_content("#results"))
    check("no answer box or Skip button once the time is up", not visible(page, "answer") and not visible(page, "test-buttons"))
    page.keyboard.press("Enter")
    page.wait_for_timeout(200)
    check("Enter right at the buzzer keeps the results", visible(page, "results"))
    page.wait_for_timeout(1000)  # the slow refill lands in here
    check("a refill landing after the buzzer shows nothing",
          page.text_content("#question") == "time!" and page.evaluate("state.current === null") and visible(page, "results"))
    page.keyboard.press("Enter")
    check("Enter a second later counts down for a new round", page.text_content("#question") == "3")
    page.keyboard.press("Escape")
    page.wait_for_timeout(2500)
    check("Esc during the countdown leaves no round running",
          visible(page, "home") and page.evaluate("state.testEndsAt === 0 && state.current === null"))

    before = saved_count(page)
    page.click("[data-mode=test]")
    running()
    page.keyboard.type(str(answer()))
    page.wait_for_timeout(50)
    page.keyboard.press("Escape")
    page.click("[data-mode=practice]")
    page.reload()
    home()
    page.wait_for_timeout(300)
    check("an abandoned test is never saved, even if the tab closes later", saved_count(page) == before)

    # failures
    page.reload()
    home()
    fail(page, "/api/questions", 1)
    page.click("[data-mode=practice]")
    page.click("#play")
    page.wait_for_function("$('feedback').textContent.includes('Could not load')", timeout=10000)
    check("failed load says so and offers retry", "Enter to retry" in page.text_content("#feedback") and visible(page, "retry"))
    page.keyboard.press("Enter")
    playing()
    check("Enter after a failed load retries and shows a question", page.evaluate("state.current !== null") and not visible(page, "retry"))
    page.keyboard.press("Escape")
    page.click("[data-mode=test]")
    running()
    page.evaluate("state.queue = []")
    fail(page, "/api/questions", 1)
    page.keyboard.press("Tab")
    page.wait_for_function("$('feedback').textContent.includes('Could not load')", timeout=10000)
    page.click("#retry")
    page.wait_for_timeout(300)
    check("a failed refill mid-test can be retried (Retry button)", page.evaluate("state.current !== null && state.testEndsAt > 0"))
    page.evaluate("state.queue = []")
    fail(page, "/api/questions", 1)
    page.keyboard.press("Tab")
    page.wait_for_function("$('feedback').textContent.includes('Could not load')", timeout=10000)
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)
    check("...and with Enter", page.evaluate("state.current !== null && state.testEndsAt > 0"))
    page.keyboard.type(str(answer()))  # one right answer, so the saved test has a score
    page.wait_for_timeout(50)
    fail(page, "/api/rounds", 1)
    before = saved_count(page)
    page.evaluate("state.testEndsAt = performance.now()")
    page.wait_for_timeout(400)
    check("a failed save says so and offers Retry",
          "Could not save results" in page.text_content("#feedback") and "Enter to retry" in page.text_content("#feedback")
          and visible(page, "retry"))
    unsaved = page.evaluate("state.unsaved.length")
    page.wait_for_timeout(700)  # past the 1-second guard: Enter must retry the save, not start a new round
    page.keyboard.press("Enter")
    page.wait_for_selector("#results:not([hidden])")
    check("Enter after a failed save saves it and shows the results",
          "score" in page.text_content("#results") and not visible(page, "retry") and saved_count(page) == before + unsaved)
    page.route("**/api/me", lambda route: route.abort())
    page.reload()
    page.wait_for_function("$('signin-message').textContent.includes('Could not reach')", timeout=10000)
    check("server down at load: Welcome says so and offers Retry", visible(page, "welcome-retry"))
    check("...and claims neither 'Sign in with Google' nor 'sign-in isn't set up'",
          not visible(page, "welcome-signin")
          and not page.evaluate("getComputedStyle(document.querySelector('[data-signin-off]')).display !== 'none'"))
    page.unroute("**/api/me")
    page.click("#welcome-retry")
    check("Retry finds you signed in again", waited(page, f"$('playing-as').textContent === {json.dumps('playing as ' + NAME)}"))

    # practice with mixed levels
    page.reload()
    home()
    page.click("[data-mode=practice]")
    page.click("label:has(input[name=level][value=mixed])")
    page.click("#play")
    playing()
    check("Practice can mix levels", page.text_content("#settings") == "practice · mixed · all levels"
          and page.evaluate("new Set([state.current, ...state.queue].map((q) => q.difficulty)).size") == 3)
    for width in [900, 400]:
        page.set_viewport_size({"width": width, "height": 800})
        page.keyboard.press("Escape")
        page.click("[data-mode=practice]")
        check(f"the four levels fit at {width}px", page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        page.keyboard.press("Escape")
    page.set_viewport_size({"width": 900, "height": 900})

    # my stats and the leaderboard
    page.reload()
    home()
    check("home lists My stats and Leaderboard", visible(page, "my-stats-choice") and visible(page, "leaderboard-choice"))
    page.click("#my-stats-choice")
    page.wait_for_function("!$('my-stats-body').textContent.includes('loading')")
    stats = page.text_content("#my-stats-body")
    check("My stats shows the test count and best", "2 taken · best" in stats)
    check("My stats has a per-topic table", page.locator("#my-stats-body table tr").count() > 1)
    page.keyboard.press("Escape")
    check("Esc goes home with My stats highlighted", visible(page, "home") and focused() == "my-stats-choice")
    page.keyboard.press("ArrowDown")
    check("down from My stats reaches Leaderboard", focused() == "leaderboard-choice")
    page.keyboard.press("Enter")
    page.wait_for_function("!$('leaderboard-list').textContent.includes('loading')")
    check("the leaderboard lists this player, highlighted and marked (you)",
          page.evaluate(f"[...document.querySelectorAll('#leaderboard-list li.me')].some((li) => li.textContent.startsWith({json.dumps(NAME)}) && li.textContent.endsWith('(you)'))"))
    page.click("#leaderboard [data-back]")
    check("Back goes home with Leaderboard highlighted", visible(page, "home") and focused() == "leaderboard-choice")
    page.route("**/api/leaderboard", lambda route: route.fulfill(json=[{"id": -1, "name": "<img src=x onerror=window.pwned=2>", "best": 99}]))
    page.click("#leaderboard-choice")
    page.wait_for_function("$('leaderboard-list').textContent.includes('99')")
    check("a name on the leaderboard is shown as text, never run as HTML",
          page.text_content("#leaderboard-list li") == "<img src=x onerror=window.pwned=2> · 99"
          and page.evaluate("!document.querySelector('#leaderboard-list img') && window.pwned === undefined"))
    page.unroute("**/api/leaderboard")
    page.keyboard.press("Escape")
    page.route("**/api/me/stats", lambda route: route.fulfill(status=500, body="down"))
    page.click("#my-stats-choice")
    check("My stats says so when it can't load", waited(page, "$('my-stats-body').textContent.includes('Could not load')"))
    page.unroute("**/api/me/stats")
    page.keyboard.press("Escape")
    page.focus("#leaderboard-choice")
    page.keyboard.press("ArrowDown")
    check("down from Leaderboard skips the hidden Sign in and reaches Account", focused() == "account-choice")
    # signing out
    page.click("#account-choice")
    page.route("**/auth/signout", lambda route: route.fulfill(status=500, body="down"))
    page.click("#sign-out")
    page.wait_for_function("$('name-error').textContent.includes('Could not sign out')")
    check("a failed sign-out says so and stays on Account", visible(page, "account"))
    page.unroute("**/auth/signout")
    page.click("#sign-out")
    page.wait_for_selector("#welcome:not([hidden])")
    check("Sign out goes to Welcome", visible(page, "welcome-signin"))
    page.reload()
    page.wait_for_selector("#welcome:not([hidden])")
    check("and stays signed out after a reload", visible(page, "welcome"))
    check("no page errors", not errors)
    print(f"{sum(results)}/{len(results)} passed", errors or "")
    browser.close()
    sys.exit(0 if all(results) else 1)
