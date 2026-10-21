// mental: the browser side. Shows questions, checks answers, times every attempt.
// Questions arrive from /api/questions already carrying their answer and worked steps.
// A finished round goes to /api/rounds, which re-checks it, saves it under the player and sends
// back its summary.
//
// Anything a person typed (a player's name) goes on the page with textContent, never innerHTML.

const TEST_SECONDS = 120;
const COUNTDOWN_MS = 700;  // per number of the 3-2-1 countdown
const QUESTIONS_PER_FETCH = { practice: 20, test: 200 };
const KEYS = {
  practice: "Enter submit / next · Tab give up · Esc quit",
  test: "type the answer · Tab skip · Esc menu",
};
const PLAYER_KEY = "mental.player";  // localStorage: id of the last player on this browser
// the server's rule too: 1-16 letters, digits, spaces, _ . - and no space at either end
const NAME_RULE = /^[A-Za-z0-9_.-]([A-Za-z0-9 _.-]{0,14}[A-Za-z0-9_.-])?$/;

const $ = (id) => document.getElementById(id);
const input = $("answer");

const state = {
  player: null,       // {id, name}
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
  testEndsAt: 0,      // 0 = no test running
  endedAt: -Infinity, // when the last round ended
  timer: null,
};

// --- players -------------------------------------------------------------------

async function getJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`server said ${response.status}`);
  return response.json();
}

// On load: straight home as the last player if they still exist; otherwise ask who's playing.
async function start() {
  let remembered = null;
  try {
    remembered = Number(localStorage.getItem(PLAYER_KEY));
  } catch {}  // storage can be blocked: then we just ask
  try {
    const player = (await getJSON("/api/players")).find((p) => p.id === remembered);
    if (player) return pickPlayer(player);
  } catch {}  // showPlayers says what went wrong
  showPlayers();
}

async function showPlayers() {
  document.activeElement?.blur();
  showScreen("players");
  $("player-error").textContent = "";
  $("new-name").value = "";
  $("player-list").replaceChildren();
  let players;
  try {
    players = await getJSON("/api/players");
  } catch (error) {
    $("player-error").textContent = `Could not reach the server (${error.message}).`;
    $("player-list").replaceChildren(menuButton("Retry", showPlayers));
    $("player-list").firstChild.focus();
    return;
  }
  if ($("players").hidden) return;  // left the screen while the list loaded
  $("player-list").replaceChildren(...players.map((p) => menuButton(p.name, () => pickPlayer(p))));
  if (!$("players").contains(document.activeElement)) {  // don't steal focus from someone typing
    const current = players.findIndex((p) => p.id === state.player?.id);
    ($("player-list").children[Math.max(current, 0)] || $("new-name")).focus();
  }
}

// A big menu button made from code; its label is text, never HTML (it can be a player's name).
function menuButton(label, onClick) {
  const button = document.createElement("button");
  button.className = "choice";
  button.dataset.nav = "";
  button.textContent = label;
  button.addEventListener("click", onClick);
  followMouse(button);
  return button;
}

function pickPlayer(player) {
  state.player = player;
  try {
    localStorage.setItem(PLAYER_KEY, String(player.id));
  } catch {}
  showHome();
}

async function addPlayer() {
  const name = $("new-name").value.trim();
  if (!NAME_RULE.test(name)) {
    $("player-error").textContent = "A name is 1-16 letters, digits, spaces, _ . or -";
    return;
  }
  let response;
  try {
    response = await fetch("/api/players", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
  } catch (error) {
    $("player-error").textContent = `Could not reach the server (${error.message}).`;
    return;
  }
  if (response.status === 409) {
    $("player-error").textContent = "That name is taken.";
  } else if (!response.ok) {
    $("player-error").textContent = `Could not add the player (server said ${response.status}).`;
  } else {
    pickPlayer(await response.json());
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
  state.current = null;
  showScreen("home");
  $("playing-as").textContent = `playing as ${state.player.name}`;
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
  const typing = document.activeElement === $("new-name");
  if (direction && !(typing && direction[0])) {  // left/right inside the name box move the caret
    nearestItem(document.activeElement, direction)?.focus();
  } else if (event.key === "Enter" && typing) {
    addPlayer();
  } else if (event.key === "Enter" && document.activeElement.tagName === "INPUT") {
    document.activeElement.click();  // tick a box or pick a level (buttons click on Enter by themselves)
  } else if (event.key === "Escape" && $("home").hidden && state.player) {
    // every menu screen goes back home (the player screen only once someone is playing)
    showHome(`${document.querySelector(".screen:not([hidden])").id}-choice`);
  } else {
    return;
  }
  event.preventDefault();
}

// The menu item nearest to `from` in direction [dx, dy]. An item counts only if it lies more in
// that direction than off to the side. Null at the edge, so the highlight stays put.
function nearestItem(from, [dx, dy]) {
  const items = [...document.querySelectorAll(".screen:not([hidden]) [data-nav]")];
  if (!items.includes(from)) return items[0];
  const box = (el) => (el.closest("label") || el).getBoundingClientRect();  // a tickbox's label is what you see
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
  const attempts = state.attempts;
  state.attempts = [];  // handed over below, so closing the tab can't send them a second time
  $("question").textContent = state.mode === "test" ? "time!" : "done!";
  input.value = "";
  showSteps([]);
  setFeedback("");
  showAnswerBox(false);
  $("retry").hidden = true;
  let saved;
  try {
    const response = await fetch("/api/rounds", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ player_id: state.player.id, mode: state.mode, attempts }),
    });
    if (!response.ok) throw new Error(`server said ${response.status}`);
    saved = await response.json();
  } catch (error) {
    if (session === state.session) setFeedback(`Could not save results (${error.message})`, "wrong");
    return;
  }
  if (session !== state.session) return;  // moved on while it saved
  showResults(saved.summary, saved.best);
}

// Closing or reloading the tab mid-practice still saves the questions already finished.
addEventListener("pagehide", () => {
  if (state.mode !== "practice" || state.finished || !state.player || state.attempts.length === 0) return;
  const body = JSON.stringify({ player_id: state.player.id, mode: "practice", attempts: state.attempts });
  navigator.sendBeacon("/api/rounds", new Blob([body], { type: "application/json" }));
  state.attempts = [];
});

const percent = (x) => `${Math.round(x * 100)}%`;
const seconds = (ms) => `${(ms / 1000).toFixed(1)}s`;
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

// Only numbers and the server's own question text, steps and topic names go into this HTML.
function showResults(summary, best) {
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
       <p class="best">${bestLine(o.score, best)}</p>
       <p>accuracy ${percent(o.accuracy)} · avg ${seconds(o.avg_time_ms)} · skipped ${o.skipped}</p>`
    : `<h2>practice done</h2>
       <p>${plural(o.count, "question")} · ${o.score} solved · first try ${percent(o.accuracy)} · gave up ${o.gave_up} · avg ${seconds(o.avg_time_ms)}</p>`;
  $("results").innerHTML = `
    ${top}
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
  document.querySelector("#my-stats [data-back]").focus();
  $("my-stats-body").textContent = "loading...";
  let stats;
  try {
    stats = await getJSON(`/api/players/${state.player.id}/stats`);
  } catch (error) {
    $("my-stats-body").textContent = `Could not load your stats (${error.message}).`;
    return;
  }
  if ($("my-stats").hidden) return;  // left the screen while it loaded
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
  document.querySelector("#leaderboard [data-back]").focus();
  const list = $("leaderboard-list");
  list.replaceChildren(listItem("loading...", "note"));
  let rows;
  try {
    rows = await getJSON("/api/leaderboard");
  } catch (error) {
    list.replaceChildren(listItem(`Could not load the leaderboard (${error.message}).`, "note"));
    return;
  }
  if ($("leaderboard").hidden) return;
  if (rows.length === 0) return list.replaceChildren(listItem("no tests yet", "note"));
  // names are typed by people: listItem puts them in as text
  list.replaceChildren(...rows.map((r) => listItem(`${r.name} · ${r.best}`, r.id === state.player.id ? "me" : "")));
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
$("add-player").addEventListener("click", addPlayer);
$("players-choice").addEventListener("click", () => showPlayers());
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
