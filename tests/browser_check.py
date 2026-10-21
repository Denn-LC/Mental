"""Drive the page in a headless browser and check the keyboard flows and race fixes.

Not part of `pytest` (it needs a running server and a browser):

    uv run mental                                   # in one terminal
    uv run --with playwright python tests/browser_check.py http://127.0.0.1:8000/

Set CHROMIUM=/path/to/chrome to use a browser Playwright didn't install itself.
"""
import os
import sys

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/"
EXE = os.environ.get("CHROMIUM")
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


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=EXE) if EXE else p.chromium.launch()
    page = browser.new_page(viewport={"width": 900, "height": 900})
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(URL)
    answer = lambda: page.evaluate("state.current.answer")
    playing = lambda: page.wait_for_function("state.current && !state.countingDown", timeout=10000)
    running = lambda: page.wait_for_function("state.testEndsAt > 0", timeout=10000)
    focused = lambda: page.evaluate("document.activeElement.dataset.mode || document.activeElement.id || document.activeElement.value")

    # home screen
    check("opens on home with Free Play highlighted", visible(page, "home") and not visible(page, "game") and focused() == "free")
    check("the title is near the top (not touching it), centred",
          page.evaluate("(() => { const r = document.querySelector('h1').getBoundingClientRect(); return r.top > 40 && r.top < 100 && Math.abs(r.left + r.width / 2 - innerWidth / 2) < 5; })()"))
    check("the home buttons sit in the middle of the screen", centre_y(page, "#home .choice:last-of-type") < 0.1)
    page.keyboard.press("ArrowDown")
    check("arrow down highlights Test Yourself", focused() == "test")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowRight")
    check("arrows stop at the edge instead of wrapping", focused() == "test")
    page.keyboard.press("ArrowUp")
    check("arrow up goes back up", focused() == "free")
    test_box = page.locator("[data-mode=test]").bounding_box()
    page.hover("[data-mode=test]")
    check("the highlight follows the mouse", focused() == "test")
    page.keyboard.press("ArrowUp")
    page.keyboard.down("Enter")
    check("Enter on Free Play opens its options, Play highlighted", visible(page, "options") and focused() == "play")
    page.keyboard.down("Enter")  # the key is still held: this one is a repeat
    page.keyboard.up("Enter")
    check("holding Enter doesn't run on into Play", visible(page, "options") and focused() == "play")
    check("the options sit in the middle of the screen", centre_y(page, "#options fieldset:last-of-type") < 0.1)

    # free play options: the arrows move the way they point (topics are a 3 x 2 grid at this width)
    page.keyboard.press("ArrowUp")
    check("up from Play reaches a level", focused() in ("1", "2", "3"))
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
          not visible(page, "answer") and not visible(page, "free-buttons") and not visible(page, "test-buttons"))
    countdown_at = centre_y(page, "#question")
    check("the countdown number is big and in the middle of the screen",
          page.evaluate("parseFloat(getComputedStyle($('question')).fontSize) >= 64") and countdown_at < 0.06)
    page.keyboard.type("5")
    page.keyboard.press("Enter")
    check("Enter during the countdown does nothing", page.evaluate("state.countingDown && state.attempts.length === 0"))
    playing()
    check("then a question, with the chosen settings", page.text_content("#settings") == "free play · multiplication · level 2" and page.input_value("#answer") == "")
    check("the answer box and Free Play's buttons appear with the question",
          visible(page, "answer") and visible(page, "free-buttons") and not visible(page, "test-buttons"))
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

    # free play
    page.keyboard.type(str(answer() * 5))
    page.keyboard.press("Enter")
    way = page.text_content("#feedback")
    page.keyboard.press("Control+a")
    page.keyboard.type(str(answer() + 1))
    page.keyboard.press("Enter")
    close = page.text_content("#feedback")
    check(f"free play: far answer gets a 'way off' line ({way!r}), off-by-one a close one ({close!r})",
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
    page.mouse.move(test_box["x"] + 20, test_box["y"] + 20)  # rest the pointer where Test Yourself will appear
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    check("Esc in a game goes home with Free Play highlighted, even under a resting pointer",
          visible(page, "home") and focused() == "free")

    # test mode
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    check("Test Yourself goes straight to the countdown (no options)", visible(page, "game") and page.text_content("#question") == "3")
    running()
    check("test mode shows a Skip button, not Free Play's buttons", visible(page, "test-buttons") and not visible(page, "free-buttons"))
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

    # failures
    page.reload()
    fail(page, "/api/questions", 1)
    page.click("[data-mode=free]")
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
    fail(page, "/api/summary")
    page.evaluate("state.testEndsAt = performance.now()")
    page.wait_for_timeout(400)
    check("results failure shows a message", "Could not load results" in page.text_content("#feedback"))

    check("no page errors", not errors)
    print(f"{sum(results)}/{len(results)} passed", errors or "")
    browser.close()
    sys.exit(0 if all(results) else 1)
