// mental: the browser side. Shows questions, checks answers, times every attempt.
// Questions arrive from /api/questions already carrying their answer, hints and steps.

const CATEGORIES = ["mixed", "addition", "subtraction", "multiplication", "division", "percentage", "relationship"];
const KEYS = "Enter submit / next · H hint · Tab skip · C category · D level";

const $ = (id) => document.getElementById(id);
const input = $("answer");

const state = {
  mode: "free",
  category: "mixed",
  difficulty: 1,
  queue: [],          // fetched questions not shown yet
  current: null,      // question on screen
  attempt: null,      // attempt record for the current question
  shownAt: 0,
  solved: false,      // answered, waiting for Enter
  streak: 0,
  attempts: [],
};

async function fetchQuestions(count) {
  const params = new URLSearchParams({ category: state.category, difficulty: state.difficulty, count });
  const response = await fetch(`/api/questions?${params}`);
  if (!response.ok) throw new Error(`server said ${response.status}`);
  return response.json();
}

async function nextQuestion() {
  try {
    if (state.queue.length === 0) state.queue = await fetchQuestions(20);
  } catch (error) {
    setFeedback(`Could not load questions (${error.message})`, "wrong");
    return;
  }
  showQuestion(state.queue.shift());
}

function showQuestion(q) {
  state.current = q;
  state.solved = false;
  state.attempt = {
    question_id: q.id, seed: q.seed, text: q.text, category: q.category, strategy: q.strategy,
    difficulty: q.difficulty, answer: q.answer, given: "", correct: false, skipped: false,
    wrong_tries: [], hints_used: 0, time_ms: 0, mode: state.mode,
  };
  state.shownAt = performance.now();
  $("question").textContent = q.text;
  showLines([]);
  setFeedback("");
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
  const clean = correct && a.wrong_tries.length === 0 && a.hints_used === 0;
  setStreak(clean ? state.streak + 1 : 0);
  $("score").textContent = `score ${state.attempts.filter((x) => x.correct).length}`;
}

function submit() {
  const value = parseAnswer(input.value);
  if (value === null) return;
  if (value === state.current.answer) {
    finishAttempt(true);
    state.solved = true;
    setFeedback("correct!  Enter for the next one", "right");
    showLines(state.current.steps);
    return;
  }
  state.attempt.wrong_tries.push(input.value);
  setFeedback("not quite", "wrong");
  input.select();
}

function hint() {
  if (!state.current || state.solved) return;
  const a = state.attempt;
  a.hints_used = Math.min(3, a.hints_used + 1);
  const lines = state.current.hints.slice(0, Math.min(a.hints_used, 2));
  if (a.hints_used === 3) lines.push(...state.current.steps);
  showLines(lines);
}

function skip() {
  if (!state.current || state.solved) return;
  finishAttempt(false, true);
  nextQuestion();
}

function onInput() {
  // allow digits and one leading minus only
  const cleaned = input.value.replace(/[^\d\-−]/g, "").replace(/(?!^)[-−]/g, "");
  if (cleaned !== input.value) input.value = cleaned;
}

function onEnter() {
  if (state.solved) return nextQuestion();
  if (state.current) submit();
}

// --- settings and display ---------------------------------------------------

function cycleCategory() {
  state.category = CATEGORIES[(CATEGORIES.indexOf(state.category) + 1) % CATEGORIES.length];
  settingsChanged();
}

function cycleDifficulty() {
  state.difficulty = (state.difficulty % 3) + 1;
  settingsChanged();
}

function settingsChanged() {
  state.queue = [];
  renderSettings();
  nextQuestion();
}

function renderSettings() {
  $("mode").textContent = "free play";
  $("category").textContent = state.category;
  $("difficulty").textContent = `level ${state.difficulty}`;
  $("timer").hidden = true;
  $("keys").textContent = KEYS;
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

function showLines(lines) {
  $("help").replaceChildren(...lines.map((line) => {
    const li = document.createElement("li");
    li.textContent = line;
    return li;
  }));
}

// --- keyboard ----------------------------------------------------------------

document.addEventListener("keydown", (event) => {
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  input.focus();
  const key = event.key.toLowerCase();
  if (key === "enter") onEnter();
  else if (key === "tab") skip();
  else if (key === "h") hint();
  else if (key === "c") cycleCategory();
  else if (key === "d") cycleDifficulty();
  else return;  // anything else (digits, minus, backspace) types normally
  event.preventDefault();
});

input.addEventListener("input", onInput);

renderSettings();
nextQuestion();
