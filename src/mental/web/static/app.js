// mental: the browser side. Shows questions, checks answers, times every attempt.
// Questions arrive from /api/questions already carrying their answer and worked steps.
// A finished round goes to /api/rounds, which re-checks it, saves it when someone is signed in
// (the server knows who from the session cookie) and sends back its summary.
//
// Anything a person typed (a display name) goes on the page with textContent, never innerHTML.

const TEST_SECONDS = 120;
const COUNTDOWN_MS = 700;  // per number of the 3-2-1 countdown
const QUESTIONS_PER_FETCH = { practice: 20, test: 200 };
const KEYS = {
  practice: "Enter submit / next · Tab give up · Esc quit",
  test: "type the answer · Tab skip · Esc menu",
};
// the server's rule too: 1-16 letters, digits, spaces, _ . - and no space at either end
const NAME_RULE = /^[A-Za-z0-9_.-]([A-Za-z0-9 _.-]{0,14}[A-Za-z0-9_.-])?$/;

const $ = (id) => document.getElementById(id);
const input = $("answer");

const state = {
  me: null,           // {signed_in, name, google} from /api/me
  mode: "practice",   // "practice" | "test"
  category: "mixed",  // for /api/questions: "mixed" or a comma-separated list
  difficulty: "1",    // "1", "2", "3" or "mixed" (each question gets a random level)
  session: 0,         // goes up on every new game or return to the menu; stale fetches check it
  loading: false,     // a question fetch is in flight
  queue: [],          // fetched questions not shown yet
  seen: {},           // question id -> question, for the results screen
  current: null,      // question on screen (null while counting down, loading or between rounds)
  countingDown: false,
  finished: false,    // the round is over: its results are saving or showing
  attempt: null,      // attempt record for the current question
  shownAt: 0,
  solved: false,      // practice: answered or given up, waiting for Enter
  streak: 0,
  attempts: [],       // finished attempts of this round, not saved yet
  unsaved: null,      // a finished round whose save failed: Enter or Retry tries again
  saving: null,       // {session, keepalive} while a round save is in flight
  screenLoad: 0,      // goes up each time a menu screen starts loading; stale loads check it
  savingName: false,
  testEndsAt: 0,      // 0 = no test running
  endedAt: -Infinity, // when the last round ended
  timer: null,
};

// --- signing in ------------------------------------------------------------------

async function getJSON(url) {
  const response = await fetch(url, { signal: AbortSignal.timeout(10000) });  // a hung server ends in an error
  if (!response.ok) throw Object.assign(new Error(`server said ${response.status}`), { status: response.status });
  return response.json();
}

const SIGNIN_MESSAGES = {
  cancelled: "Sign-in cancelled.",
  failed: "Sign-in failed, please try again.",
  unavailable: "Sign-in isn't set up here.",
};

// On load: signed in -> home (or the display-name screen the first time); otherwise Welcome.
async function start() {
  const outcome = new URLSearchParams(location.search).get("signin");
  if (outcome) history.replaceState(null, "", "/");  // a reload must not show the message again
  $("welcome-retry").hidden = true;
  try {
    state.me = await getJSON("/api/me");
  } catch (error) {
    state.me = { signed_in: false, name: null, google: false, unreachable: true };  // claim neither sign-in line
    renderMe();
    $("welcome-retry").hidden = false;
    return showWelcome(`Could not reach the server (${error.message}).`);
  }
  renderMe();
  if (!state.me.signed_in) return showWelcome(SIGNIN_MESSAGES[outcome] || "");
  if (state.me.name === null) return showAccount();
  showHome();
}

// Shows or hides everything that depends on who is playing (see the data-* attributes in index.html).
function renderMe() {
  const { signed_in: member, google, unreachable } = state.me;
  const shown = {
    "data-member-only": member,
    "data-signin": !member && google && !unreachable,
    "data-signin-off": !member && !google && !unreachable,
  };
  for (const [attribute, visible] of Object.entries(shown)) {
    for (const element of document.querySelectorAll(`[${attribute}]`)) element.hidden = !visible;
  }
  $("playing-as").textContent = member ? `playing as ${state.me.name}` : "playing as guest · nothing is saved";
}

function focusFirst(screenId) {
  document.querySelector(`#${screenId} [data-nav]:not([hidden])`)?.focus();
}

function showWelcome(message = "") {
  document.activeElement?.blur();
  showScreen("welcome");
  $("signin-message").textContent = message;
  focusFirst("welcome");
}

function signIn() {
  location.assign("/auth/google");  // Google's account chooser, then back to /auth/callback
}

async function signOut() {
  try {
    const response = await fetch("/auth/signout", { method: "POST" });
    if (!response.ok) throw new Error(`server said ${response.status}`);
  } catch (error) {  // the session may still be live, so stay where you are rather than pretend
    $("name-error").textContent = `Could not sign out (${error.message}).`;
    return;
  }
  state.me = { ...state.me, signed_in: false, name: null };
  renderMe();
  showWelcome();
}

// Account screen; the first time after signing in it asks for a display name instead.
function showAccount() {
  const first = state.me.name === null;
  showScreen("account");
  $("account-title").textContent = first ? "pick a display name" : "account";
  $("account-back").hidden = first;
  $("name-error").textContent = "";
  $("name-box").value = state.me.name || "";
  $("name-box").focus();
}

async function saveName() {
  const name = $("name-box").value.trim();
  if (!NAME_RULE.test(name)) {
    $("name-error").textContent = "A name is 1-16 letters, digits, spaces, _ . or -";
    return;
  }
  if (state.savingName) return;  // a second Enter while the first is on its way
  state.savingName = true;
  let response;
  try {
    response = await fetch("/api/me/name", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
  } catch (error) {
    $("name-error").textContent = `Could not reach the server (${error.message}).`;
    return;
  } finally {
    state.savingName = false;
  }
  if (response.status === 409) {
    $("name-error").textContent = "That name is taken.";
  } else if (response.status === 401) {
    state.me = { ...state.me, signed_in: false, name: null };
    renderMe();
    showWelcome("You were signed out. Please sign in again.");
  } else if (!response.ok) {
    $("name-error").textContent = `Could not save the name (server said ${response.status}).`;
  } else {
    const first = state.me.name === null;
    state.me.name = name;
    renderMe();
    showHome(first ? undefined : "account-choice");
  }
}

// --- menus -----------------------------------------------------------------

function showScreen(id) {
  for (const screen of document.querySelectorAll(".screen")) screen.hidden = screen.id !== id;
}

// focusId: the home choice to highlight (the one you came back from); else the last mode played.
function showHome(focusId) {
  stopTest();
  state.session++;  // anything still loading for the old game is dropped
  state.loading = false;
  state.countingDown = false;
  state.finished = false;
  state.attempts = [];  // an abandoned test is never saved
  state.unsaved = null;
  state.current = null;
  showScreen("home");
  renderMe();
  ($(focusId) || document.querySelector(`#home [data-mode=${state.mode}]`)).focus();
}

function showOptions() {
  showScreen("options");
  $("menu-error").textContent = "";
  $("play").focus();
}

function chooseMode(mode) {
  state.mode = mode;
  if (mode === "practice") return showOptions();
  state.category = "mixed";
  state.difficulty = "mixed";
  startGame();
}

function playPractice() {
  const ticked = [...document.querySelectorAll("input[name=topic]:checked")].map((box) => box.value);
  if (ticked.length === 0) {
    $("menu-error").textContent = "Tick at least one topic.";
    return;
  }
  state.category = ticked.length === document.querySelectorAll("input[name=topic]").length ? "mixed" : ticked.join(",");
  state.difficulty = document.querySelector("input[name=level]:checked").value;
  startGame();
}

// Arrow keys move the highlight the way they point; Enter or Space picks the item.
function onMenuKey(event) {
  const direction = { ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0] }[event.key];
  const typing = document.activeElement === $("name-box");
  if (direction && !(typing && direction[0])) {  // left/right inside the name box move the caret
    nearestItem(document.activeElement, direction)?.focus();
  } else if (event.key === "Enter" && typing) {
    saveName();
  } else if (event.key === "Enter" && document.activeElement.tagName === "INPUT") {
    document.activeElement.click();  // tick a box or pick a level (buttons click on Enter by themselves)
  } else if (!$("account").hidden && !typing && event.key.length === 1 && event.key !== " ") {
    $("name-box").focus();  // typing a name lands in the name box wherever the highlight is
    return;
  } else if (event.key === "Escape" && !$("account").hidden && state.me.name === null) {
    signOut();  // leaving the first display-name screen signs back out
  } else if (event.key === "Escape" && $("home").hidden && $("welcome").hidden && state.me) {
    // every other menu screen goes back home, highlighting the choice it was opened from
    showHome(`${document.querySelector(".screen:not([hidden])").id}-choice`);
  } else {
    return;
  }
  event.preventDefault();
}

// The menu item nearest to `from` in direction [dx, dy]. An item counts only if it lies more in
// that direction than off to the side. Null at the edge, so the highlight stays put.
function nearestItem(from, [dx, dy]) {
  const box = (el) => (el.closest("label") || el).getBoundingClientRect();  // a tickbox's label is what you see
  const shown = (el) => !el.hidden && (box(el).width > 0 || box(el).height > 0);  // hidden items can't be chosen
  const items = [...document.querySelectorAll(".screen:not([hidden]) [data-nav]")].filter(shown);
  if (!items.includes(from)) return items[0];
  const gap = (v, low, high) => Math.max(low - v, 0, v - high);  // 0 when v is within [low, high]
  const here = box(from);
  const x = here.left + here.width / 2;
  const y = here.top + here.height / 2;
  let best = null;
  let bestScore = Infinity;
  for (const item of items) {
    const b = box(item);
    const ahead = (b.left + b.width / 2 - x) * dx + (b.top + b.height / 2 - y) * dy;
    const aside = dx ? gap(y, b.top, b.bottom) : gap(x, b.left, b.right);
    const score = ahead + aside * 3;
    if (ahead > 1 && aside < ahead && score < bestScore) {
      best = item;
      bestScore = score;
    }
  }
  return best;
}

function startGame() {
  showScreen("game");
  renderSettings();
  startRound();
}

// A round: 3-2-1 countdown while the questions load, then go (and start the clock in test mode).
async function startRound() {
  state.session++;
  const session = state.session;
  stopTest();
  state.loading = false;
  state.countingDown = true;
  state.finished = false;
  state.current = null;
  state.queue = [];
  state.attempts = [];
  state.seen = {};
  setStreak(0);
  $("score").textContent = "score 0";
  $("timer").textContent = clock(TEST_SECONDS);
  $("results").hidden = true;
  input.value = "";
  showSteps([]);
  setFeedback("");
  renderButtons();
  showAnswerBox(false);
  $("retry").hidden = true;
  $("game").classList.add("counting");
  const fetching = fetchQuestions(QUESTIONS_PER_FETCH[state.mode]).catch((error) => error);
  for (const n of [3, 2, 1]) {
    $("question").textContent = n;
    await new Promise((done) => setTimeout(done, COUNTDOWN_MS));
    if (session !== state.session) return;  // Esc during the countdown
  }
  const questions = await fetching;
  if (session !== state.session) return;
  state.countingDown = false;
  $("game").classList.remove("counting");
  if (questions instanceof Error) return showLoadError(questions);
  state.queue = questions;
  showQuestion(state.queue.shift());
  if (state.mode === "test") {
    state.testEndsAt = performance.now() + TEST_SECONDS * 1000;
    state.timer = setInterval(tick, 100);
  }
}

// --- questions -------------------------------------------------------------

async function fetchQuestions(count) {
  const params = new URLSearchParams({ category: state.category, difficulty: state.difficulty, count });
  return getJSON(`/api/questions?${params}`);
}

async function nextQuestion() {
  if (state.queue.length === 0) {
    if (state.loading) return;  // already fetching
    const session = state.session;
    state.loading = true;
    state.current = null;  // nothing on screen to answer or skip while loading
    state.solved = false;
    $("question").textContent = "";
    showSteps([]);
    setFeedback("");
    showAnswerBox(false);
    $("retry").hidden = true;
    try {
      const questions = await fetchQuestions(QUESTIONS_PER_FETCH[state.mode]);
      if (session !== state.session) return;  // went back to the menu while loading
      state.queue = questions;
    } catch (error) {
      if (session === state.session) showLoadError(error);
      return;
    } finally {
      if (session === state.session) state.loading = false;
    }
  }
  showQuestion(state.queue.shift());
}

// Shown when questions fail to load. The Retry button lets the mouse do what Enter does.
function showLoadError(error) {
  $("question").textContent = "";
  setFeedback(`Could not load questions (${error.message}). Enter to retry.`, "wrong");
  $("retry").hidden = false;
}

function showQuestion(q) {
  state.current = q;
  $("retry").hidden = true;
  state.seen[q.id] = q;
  state.solved = false;
  state.attempt = {
    question_id: q.id, seed: q.seed, text: q.text, category: q.category, strategy: q.strategy,
    difficulty: q.difficulty, answer: q.answer, given: "", correct: false, skipped: false,
    wrong_tries: [], gave_up: false, time_ms: 0, mode: state.mode,
  };
  state.shownAt = performance.now();  // practice times every question too, without showing it
  $("question").textContent = q.text;
  showSteps([]);
  setFeedback("");
  renderButtons();
  showAnswerBox(true);
  input.value = "";
  input.focus();
}

// "−465" and "-465" both mean -465. Anything that isn't a whole number gives null.
function parseAnswer(text) {
  const clean = text.replace("−", "-");
  return /^-?\d+$/.test(clean) ? Number(clean) : null;
}

function finishAttempt(correct, skipped = false) {
  const a = state.attempt;
  a.given = input.value;
  a.correct = correct;
  a.skipped = skipped;
  a.time_ms = Math.round(performance.now() - state.shownAt);
  state.attempts.push(a);
  setStreak(correct && a.wrong_tries.length === 0 ? state.streak + 1 : 0);
  $("score").textContent = `score ${state.attempts.filter((x) => x.correct).length}`;
}

function submit() {
  const value = parseAnswer(input.value);
  if (value === null) return;
  if (value === state.current.answer) {
    finishAttempt(true);
    state.solved = true;
    setFeedback("correct!  Enter for the next one", "right");
    showSteps(state.current.steps);
    renderButtons();
    return;
  }
  if (input.value === state.attempt.wrong_tries.at(-1)) return;  // same wrong value again
  state.attempt.wrong_tries.push(input.value);
  setFeedback(wrongLine(value, state.current.answer), "wrong");
  input.select();
}

// What to say after a wrong answer depends on how far off it was.
const WRONG_LINES = {
  close: ["almost!", "so close", "nearly there", "off by a hair"],
  off: ["not quite", "nope, try again", "not it", "try again"],
  way: ["are you even trying?", "jesus.", "that's not even close", "...what?", "bold guess"],
};
let lastWrongLine = "";

function wrongLine(given, answer) {
  const diff = Math.abs(given - answer);
  const gap = diff / Math.max(Math.abs(answer), 10);  // how far off, as a share of the answer
  const wrongSign = given * answer < 0;
  const tier = wrongSign || gap > 0.5 ? "way" : diff <= 1 || gap <= 0.05 ? "close" : "off";
  const options = WRONG_LINES[tier].filter((line) => line !== lastWrongLine);
  lastWrongLine = options[Math.floor(Math.random() * options.length)];
  return lastWrongLine;
}

function giveUp() {
  if (!state.current || state.solved) return;
  state.attempt.gave_up = true;
  finishAttempt(false);
  state.solved = true;
  const answer = state.current.steps.at(-1).split(" = ")[1];  // already formatted, e.g. "1,480"
  setFeedback(`the answer is ${answer}.  Enter for the next one`, "wrong");
  showSteps(state.current.steps);
  renderButtons();
}

function skip() {
  if (!state.current || !state.testEndsAt) return;  // only during a running test
  finishAttempt(false, true);
  nextQuestion();
}

// Quit (button or Esc): the question on screen is not recorded; the rest is saved and summed up.
function quitPractice() {
  if (state.finished) return;
  if (state.attempts.length === 0) return showHome();
  endRound();
}

function onInput() {
  // allow one leading minus and up to 5 digits (no answer is longer)
  const cleaned = input.value.replace(/[^\d\-−]/g, "").replace(/(?!^)[-−]/g, "").replace(/^([-−]?\d{0,5}).*$/, "$1");
  if (cleaned !== input.value) input.value = cleaned;
  // test mode accepts the right answer as soon as it is typed
  if (state.mode === "test" && state.testEndsAt && state.current &&
      parseAnswer(input.value) === state.current.answer) {
    finishAttempt(true);
    nextQuestion();
  }
}

function onEnter() {
  if (state.countingDown) return;
  if (state.finished && state.unsaved) return saveRound();  // the save failed: try again
  if (state.finished || (state.mode === "test" && !state.testEndsAt)) {
    // between rounds, or the test's first load failed. A late Enter from the last answer must
    // not skip straight past the results.
    if (performance.now() - state.endedAt > 1000) startRound();
    return;
  }
  if (state.mode === "test") return state.current ? recordWrongTry() : nextQuestion();  // no question: retry the load
  if (!state.current || state.solved) return nextQuestion();  // also retries a failed load
  submit();
}

// Esc quits practice (with its summary); anywhere else in a game it goes home.
function onEscape() {
  if (state.mode === "practice" && !state.finished && !state.countingDown) quitPractice();
  else showHome();
}

// Test mode gives no feedback on a wrong answer (that would be a hint), but keeps it for the stats.
function recordWrongTry() {
  const value = parseAnswer(input.value);
  if (!state.current || value === null || value === state.current.answer) return;
  if (input.value !== state.attempt.wrong_tries.at(-1)) state.attempt.wrong_tries.push(input.value);
}

// --- the end of a round --------------------------------------------------------

const clock = (seconds) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

function tick() {
  const left = state.testEndsAt - performance.now();
  $("timer").textContent = clock(Math.max(0, Math.ceil(left / 1000)));
  if (left <= 0) endRound();
}

function stopTest() {
  clearInterval(state.timer);
  state.testEndsAt = 0;
}

// The test's buzzer or quitting practice: save the round, then show what the server made of it.
async function endRound() {
  stopTest();
  state.session++;  // a question refill still in flight must not show up over the results
  const session = state.session;
  state.finished = true;
  state.current = null;  // the unfinished question is not recorded
  state.endedAt = performance.now();
  state.unsaved = state.attempts;
  state.attempts = [];  // handed over to saveRound, so closing the tab can't send them a second time
  $("question").textContent = state.mode === "test" ? "time!" : "done!";
  input.value = "";
  showSteps([]);
  setFeedback("");
  showAnswerBox(false);
  $("retry").hidden = true;
  saveRound();
}

// Browsers refuse keepalive requests over 64KB, so only small saves (a test, a normal practice
// session) are asked to survive the tab closing.
const KEEPALIVE_LIMIT = 60000;

async function saveRound() {
  const session = state.session;
  if (state.saving?.session === session) return;  // this round is already on its way
  const attempts = state.unsaved;
  const body = JSON.stringify({ mode: state.mode, attempts });
  const keepalive = body.length < KEEPALIVE_LIMIT;
  state.saving = { session, keepalive };
  $("retry").hidden = true;
  setFeedback("saving...");
  let saved;
  try {
    const response = await fetch("/api/rounds", {
      method: "POST",
      keepalive,
      headers: { "Content-Type": "application/json" },
      body,
      signal: AbortSignal.timeout(15000),  // a hung server ends in the retry message, not a frozen screen
    });
    if (!response.ok) throw new Error(`server said ${response.status}`);
    saved = await response.json();
  } catch (error) {
    if (session === state.session) {
      setFeedback(`Could not save results (${error.message}). Enter to retry.`, "wrong");
      $("retry").hidden = false;
    }
    return;
  } finally {
    if (state.saving?.session === session) state.saving = null;
  }
  if (state.unsaved === attempts) state.unsaved = null;
  if (session !== state.session) return;  // moved on while it saved
  setFeedback("");
  if (!saved.saved && state.me.signed_in) {  // the session ended meanwhile: find out, so the page says so
    try {
      state.me = await getJSON("/api/me");
      renderMe();
    } catch {}
    if (session !== state.session) return;
  }
  showResults(saved.summary, saved.best, saved.saved);
}

// Closing or reloading the tab mid-practice still saves the questions already finished.
// Beacons in flight are capped at about 64KB in all, so a long session goes in pieces of
// BEACON_CHUNK attempts until the browser refuses one: the first ~250 questions get through.
const BEACON_CHUNK = 100;

addEventListener("pagehide", () => {
  if (state.mode !== "practice" || !state.me?.signed_in || !state.me.name) return;  // guests have nothing to save
  // a finished round whose save is already on its way with keepalive arrives by itself
  const attempts = !state.finished ? state.attempts : state.saving?.keepalive ? [] : state.unsaved || [];
  for (let i = 0; i < attempts.length; i += BEACON_CHUNK) {
    const body = JSON.stringify({ mode: "practice", attempts: attempts.slice(i, i + BEACON_CHUNK) });
    if (!navigator.sendBeacon("/api/rounds", new Blob([body], { type: "application/json" }))) break;
  }
  state.attempts = [];
  state.unsaved = null;
});

const percent = (x) => `${Math.round(x * 100)}%`;
const seconds = (ms) => `${(ms / 1000).toFixed(1)}s`;
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

// Only numbers and the server's own question text, steps and topic names go into this HTML.
function showResults(summary, best, saved) {
  state.endedAt = performance.now();  // the 1-second Enter guard counts from when the results appear
  const o = summary.overall;
  const rows = Object.entries(summary.by_category)
    .map(([name, s]) => `<tr><td>${name}</td><td>${s.score}/${s.count}</td><td>${percent(s.accuracy)}</td><td>${seconds(s.avg_time_ms)}</td></tr>`)
    .join("");
  const slowest = summary.slowest
    .map((id) => state.seen[id])
    .map((q) => `<li>${q.text}<br><small>${q.steps.join("  →  ")}</small></li>`)
    .join("");
  const top = state.mode === "test"
    ? `<h2>score ${o.score}</h2>
       ${best ? `<p class="best">${bestLine(o.score, best)}</p>` : ""}
       <p>accuracy ${percent(o.accuracy)} · avg ${seconds(o.avg_time_ms)} · skipped ${o.skipped}</p>`
    : `<h2>practice done</h2>
       <p>${plural(o.count, "question")} · ${o.score} solved · first try ${percent(o.accuracy)} · gave up ${o.gave_up} · avg ${seconds(o.avg_time_ms)}</p>`;
  $("results").innerHTML = `
    ${top}
    ${saved ? "" : `<p class="best">not saved · sign in to keep your scores</p>`}
    <table><tr><th>category</th><th>solved</th><th>first try</th><th>avg</th></tr>${rows}</table>
    <h3>slowest: learn these</h3><ol>${slowest}</ol>
    <p>Enter to go again · Esc for the menu</p>`;
  $("results").hidden = false;
}

// best = {previous, best} from the server; previous is null before the first test.
function bestLine(score, best) {
  if (best.previous === null) return `first test · best ${best.best}`;
  if (score > best.previous) return `new best! (was ${best.previous})`;
  return `best ${best.best}`;
}

// --- my stats and the leaderboard --------------------------------------------

async function showMyStats() {
  showScreen("my-stats");
  focusFirst("my-stats");
  if (!state.me.signed_in) return;  // guests see the sign-in prompt instead
  $("my-stats-body").textContent = "loading...";
  const load = ++state.screenLoad;
  let stats;
  try {
    stats = await getJSON("/api/me/stats");
  } catch (error) {
    if (load !== state.screenLoad) return;
    if (error.status === 401) {  // the session ended (expired, or signed out elsewhere)
      state.me = { ...state.me, signed_in: false, name: null };
      renderMe();
      return focusFirst("my-stats");
    }
    $("my-stats-body").textContent = `Could not load your stats (${error.message}).`;
    return;
  }
  if (load !== state.screenLoad || $("my-stats").hidden) return;  // left or reloaded the screen meanwhile
  const t = stats.tests;
  const recent = t.recent
    .map((r) => `<li>${r.score} <small>${new Date(r.at).toLocaleDateString()}</small></li>`)
    .join("");
  const rows = Object.entries(stats.by_category)
    .map(([name, s]) => `<tr><td>${name}</td><td>${s.count}</td><td>${s.score}</td><td>${percent(s.accuracy)}</td><td>${seconds(s.avg_time_ms)}</td></tr>`)
    .join("");
  // only numbers, dates and the server's topic names go into this HTML: nothing anyone typed
  $("my-stats-body").innerHTML = `
    <h3>tests</h3>
    <p>${t.count ? `${t.count} taken · best ${t.best}` : "no tests yet"}</p>
    ${recent ? `<ol>${recent}</ol>` : ""}
    <h3>by topic</h3>
    ${rows ? `<table><tr><th>topic</th><th>done</th><th>solved</th><th>first try</th><th>avg</th></tr>${rows}</table>` : "<p>nothing played yet</p>"}`;
}

async function showLeaderboard() {
  showScreen("leaderboard");
  focusFirst("leaderboard");
  const list = $("leaderboard-list");
  list.replaceChildren(listItem("loading...", "note"));
  const load = ++state.screenLoad;
  let rows;
  try {
    rows = await getJSON("/api/leaderboard");
  } catch (error) {
    if (load !== state.screenLoad) return;
    list.replaceChildren(listItem(`Could not load the leaderboard (${error.message}).`, "note"));
    return;
  }
  if (load !== state.screenLoad || $("leaderboard").hidden) return;  // left or reloaded the screen meanwhile
  if (rows.length === 0) return list.replaceChildren(listItem("no tests yet", "note"));
  // names are typed by people: listItem puts them in as text
  list.replaceChildren(...rows.map((r) => r.me ? listItem(`${r.name} · ${r.best} (you)`, "me") : listItem(`${r.name} · ${r.best}`, "")));
}

function listItem(text, className) {
  const li = document.createElement("li");
  li.textContent = text;
  li.className = className;
  return li;
}

// --- display -----------------------------------------------------------------

function renderSettings() {
  const topics = state.category === "mixed" ? "mixed" : state.category.replaceAll(",", ", ");
  const level = state.difficulty === "mixed" ? "all levels" : `level ${state.difficulty}`;
  $("settings").textContent = `${state.mode === "practice" ? "practice" : "test yourself"} · ${topics} · ${level}`;
  $("timer").hidden = state.mode === "practice";
  $("keys").textContent = KEYS[state.mode];
}

// The answer box and the mode's buttons only show while there is a question to answer.
function showAnswerBox(show) {
  input.hidden = !show;
  $("practice-buttons").hidden = !show || state.mode !== "practice";
  $("test-buttons").hidden = !show || state.mode !== "test";
}

function renderButtons() {
  $("submit").textContent = state.solved ? "Next" : "Enter";
  $("give-up").disabled = state.solved || !state.current;
}

function setStreak(n) {
  state.streak = n;
  $("streak").textContent = `streak ${n}`;
  document.body.dataset.heat = n >= 20 ? 3 : n >= 10 ? 2 : n >= 3 ? 1 : 0;
}

function setFeedback(text, kind = "") {
  const el = $("feedback");
  el.textContent = text;
  el.className = "";
  void el.offsetWidth;  // restart the flash animation even if the class is the same
  el.className = kind;
}

function showSteps(lines) {
  $("steps").replaceChildren(...lines.map((line) => {
    const li = document.createElement("li");
    li.textContent = line;
    return li;
  }));
}

// --- keyboard and buttons ------------------------------------------------------

document.addEventListener("keydown", (event) => {
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  // a held Enter must not run on into the next screen (home -> options -> Play)
  if (event.key === "Enter" && event.repeat) return event.preventDefault();
  if ($("game").hidden) return onMenuKey(event);
  const key = event.key;
  if (key === "Escape") onEscape();
  else if (key === "Enter" && document.activeElement.tagName !== "BUTTON") onEnter();
  else if (key === "Tab") state.mode === "test" ? skip() : giveUp();  // one "I'm stuck" key in both modes
  else {
    if (/^[\d\-−]$/.test(key)) input.focus();  // typing always lands in the answer box
    return;
  }
  event.preventDefault();
});

// The highlight follows the mouse too, but only when it really moves
// (not when a screen appears under a resting pointer).
function followMouse(item) {
  (item.closest("label") || item).addEventListener("mousemove", (event) => {
    if (event.movementX || event.movementY) item.focus();
  });
}

input.addEventListener("input", onInput);
for (const choice of document.querySelectorAll("[data-mode]")) {
  choice.addEventListener("click", () => chooseMode(choice.dataset.mode));
}
for (const item of document.querySelectorAll("[data-nav]")) followMouse(item);
$("play").addEventListener("click", playPractice);
for (const button of document.querySelectorAll("button[data-signin]")) button.addEventListener("click", signIn);
$("guest-choice").addEventListener("click", () => showHome());
$("welcome-retry").addEventListener("click", start);
$("account-choice").addEventListener("click", showAccount);
$("save-name").addEventListener("click", saveName);
$("sign-out").addEventListener("click", signOut);
$("my-stats-choice").addEventListener("click", showMyStats);
$("leaderboard-choice").addEventListener("click", showLeaderboard);
for (const back of document.querySelectorAll("[data-back]")) {
  back.addEventListener("click", () => showHome(`${back.closest(".screen").id}-choice`));
}
$("submit").addEventListener("click", () => { onEnter(); input.focus(); });
$("give-up").addEventListener("click", () => { giveUp(); input.focus(); });
$("quit").addEventListener("click", () => quitPractice());
$("skip").addEventListener("click", () => { skip(); input.focus(); });
$("retry").addEventListener("click", onEnter);

start();
