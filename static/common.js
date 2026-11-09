// Helpers shared by the drill pages.
const $ = (id) => document.getElementById(id);

function savedLesson() {
  try { return localStorage.getItem("lesson"); } catch { return null; }
}

function saveLesson(value) {
  try { localStorage.setItem("lesson", value); } catch {}
}

async function api(path, options) {
  const res = await fetch(path, options);
  refreshUsage();
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `Request failed (${res.status})`);
  return body;
}

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
}

// A spinning indicator with a message and the seconds elapsed, for slow AI work.
function spinner(message) {
  const box = el("p", "", "working");
  const text = el("span", message);
  const seconds = el("span", "", "muted");
  box.append(el("span", "", "spin"), text, seconds);
  const started = Date.now();
  const timer = setInterval(() => {
    if (!box.isConnected && Date.now() - started > 1000) {
      clearInterval(timer);
      return;
    }
    seconds.textContent = ` ${Math.floor((Date.now() - started) / 1000)}s`;
  }, 1000);
  return box;
}

// "Why is this wrong?": Haiku explains an answer Jev marked wrong. The grade itself stays as it is.
function whyButton(path, body) {
  const box = el("div", "", "why");
  const button = el("button", "Why is this wrong?");
  button.addEventListener("click", async () => {
    button.disabled = true;
    box.replaceChildren(spinner("Asking for an explanation"));
    try {
      const why = await api(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const nodes = [el("p", why.reason)];
      if (why.verdict === "correct") {
        nodes.unshift(el("p", "The explainer thinks your answer may be right. It still counts as wrong, " +
          "so compare it with the answer yourself.", "verdict-almost"));
      }
      nodes.push(el("p", "Explained by AI (unvalidated).", "muted"));
      box.replaceChildren(...nodes);
    } catch (e) {
      box.replaceChildren(el("p", e.message, "wrong"), button);
      button.disabled = false;
    }
  });
  box.append(button);
  return box;
}

function showError(message) {
  $("feedback").replaceChildren(el("p", message, "wrong"));
}

async function loadLessons() {
  const lessons = await api("/api/lessons");
  if (!lessons.length) {
    showError("No words loaded. Run the loader first (see README).");
    return false;
  }
  for (const n of lessons) $("lesson").append(new Option(`${n}`, n));
  const saved = savedLesson();
  if (saved && lessons.includes(Number(saved))) $("lesson").value = saved;
  return true;
}

// With a Korean IME, Enter can arrive while the last syllable is still being composed.
// Wait for the composition to finish so the full answer is submitted.
function onEnter(input, handler) {
  let pending = false;
  input.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    if (e.isComposing || e.keyCode === 229) pending = true;
    else handler();
  });
  input.addEventListener("compositionend", () => {
    if (pending) {
      pending = false;
      setTimeout(handler, 0);
    }
  });
}

// Scope: the lesson cap plus an optional topic. The server turns a topic name into a word
// list once per (topic, lesson) with one AI call; asking again is free.
let topic = null;  // {id, name, lesson, interpretation, count}
let scopeChanged = () => {};

function savedTopic() {
  try { return localStorage.getItem("topic"); } catch { return null; }
}

function saveTopic(name) {
  try {
    if (name) localStorage.setItem("topic", name);
    else localStorage.removeItem("topic");
  } catch {}
}

function scopeQuery() {
  return `lesson=${$("lesson").value}` + (topic ? `&topic=${topic.id}` : "");
}

function clearTopic() {
  topic = null;
  saveTopic(null);
  $("topic").value = "";
  $("topic-status").textContent = "";
}

async function applyTopic(name) {
  $("topic-status").textContent = " Finding words for this topic...";
  try {
    topic = await api("/api/topics", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, lesson: Number($("lesson").value) }),
    });
  } catch (e) {
    clearTopic();
    $("topic-status").textContent = ` ${e.message}`;
    return;
  }
  saveTopic(topic.name);
  $("topic").value = topic.name;
  const clear = el("button", "Clear topic");
  clear.addEventListener("click", () => { clearTopic(); scopeChanged(); });
  $("topic-status").replaceChildren(
    el("span", ` ${topic.count} words: ${topic.interpretation} (picked by AI, not validated) `, "muted"), clear,
  );
}

async function initScope(onChange) {
  scopeChanged = onChange;
  if (!(await loadLessons())) return false;
  const box = el("div", "", "topic");
  const input = el("input");
  input.id = "topic";
  input.placeholder = "Topic (optional), e.g. food";
  input.autocomplete = "off";
  const apply = el("button", "Apply");
  const status = el("span");
  status.id = "topic-status";
  box.append(input, apply, status);
  $("lesson").closest("label").after(box);

  const go = async () => {
    const name = input.value.trim();
    if (!name) return;
    await applyTopic(name);
    scopeChanged();
  };
  apply.addEventListener("click", go);
  onEnter(input, go);
  $("lesson").addEventListener("change", async () => {
    saveLesson($("lesson").value);
    if (topic) await applyTopic(topic.name);  // topic word lists are capped per lesson
    scopeChanged();
  });

  const saved = savedTopic();
  if (saved) await applyTopic(saved);
  return true;
}

// A word with its meaning on hover (title) or click (shown in #hint, for touch screens).
function hintSpan(text, meaning, kind) {
  const span = el("span", text, kind ? `hint ${kind}` : "hint");
  span.title = meaning;
  span.addEventListener("click", () => { $("hint").textContent = meaning; });
  return span;
}

function tokenKind(t) {
  return t.name ? "name" : t.new ? "new" : "";
}

function tokenMeaning(t) {
  const label = t.name ? " (name)" : t.new ? " (new word)" : "";
  return `${t.base} = ${t.english}${label}`;
}

// Debug panel for the demo (Words and Sentences): every learned word in scope with its
// confidence broken down, how it changed since the last refresh, and where the next pick
// comes from. Toggled with the "Debug" checkbox in the nav bar; remembered per browser.
let debugOn = false;
let debugMode = "words";
let debugExclude = null;
let lastSeen = null;  // word id -> {confidence, attempts} at the previous refresh
const DEBUG_ROWS = 20;

function initDebug(mode) {
  debugMode = mode;
  const panel = el("div");
  panel.id = "debug";
  document.body.append(panel);
  addDebugToggle((on) => {
    panel.hidden = !on;
    refreshDebug();
  });
  panel.hidden = !debugOn;
}

// The "Debug" checkbox in the nav bar. onChange(on) runs after each toggle.
function addDebugToggle(onChange) {
  debugOn = debugStored();
  const box = el("input");
  box.type = "checkbox";
  box.checked = debugOn;
  const label = el("label");
  label.append(box, " Debug");
  document.querySelector("body > p").append(" | ", label);
  box.addEventListener("change", () => {
    debugOn = box.checked;
    try { localStorage.setItem("debug", debugOn ? "1" : "0"); } catch {}
    showUsageCounter(debugOn);
    onChange(debugOn);
  });
}

function debugStored() {
  try { return localStorage.getItem("debug") === "1"; } catch { return false; }
}

// With Debug on, every page shows the AI calls made in this server run in the bottom-left corner.
let usageBox = null;

function showUsageCounter(on) {
  if (!usageBox) {
    usageBox = el("div", "", "usage-counter");
    document.body.append(usageBox);
  }
  usageBox.hidden = !on;
  refreshUsage();
}

async function refreshUsage() {
  if (!usageBox || usageBox.hidden) return;
  try {
    const u = await (await fetch("/api/usage")).json();
    usageBox.textContent = `AI calls: ${u.calls} / ${u.cap} · Jev: ${u.jev_calls}`;
  } catch {}
}

document.addEventListener("DOMContentLoaded", () => showUsageCounter(debugStored()));

const pct = (x) => `${Math.round(x * 100)}%`;

// exclude: the word on screen, which the next pick skips. Omit to keep the previous one.
async function refreshDebug(exclude) {
  if (exclude !== undefined) debugExclude = exclude;
  if (!debugOn || !$("lesson").value) return;
  let d;
  try {
    d = await api(`/api/debug?${scopeQuery()}${debugExclude ? `&exclude=${debugExclude}` : ""}`);
  } catch (e) {
    $("debug").replaceChildren(el("h2", "Debug"), el("p", e.message, "wrong"));
    return;
  }
  const pool = new Set(debugMode === "words" ? d.next_pool : d.focus_pool);
  // Compare rounded percentages, so a row only shows a change you can see.
  const changed = (w) => lastSeen && w.id in lastSeen &&
    (pct(w.confidence) !== pct(lastSeen[w.id].confidence) || w.attempts !== lastSeen[w.id].attempts);
  // Least confident first; always include rows that just changed or can be picked next.
  const rows = d.words.filter((w, i) => i < DEBUG_ROWS || changed(w) || pool.has(w.id));

  const table = el("table");
  const head = el("tr");
  for (const h of ["Word", "English", "Confidence", "Accuracy", "Time decay", "Answers since last right", "Streak", "Half-life"]) {
    head.append(el("th", h));
  }
  table.append(head);
  for (const w of rows) {
    const answered = changed(w) && w.attempts !== lastSeen[w.id].attempts;
    const tr = el("tr", "", [pool.has(w.id) ? "pool" : "", answered ? "answered" : ""].join(" ").trim());
    const conf = el("td", pct(w.confidence));
    if (changed(w)) {
      const before = lastSeen[w.id];
      if (!w.last_correct) {
        conf.append(el("span", " (not answered right yet)", "muted"));
      } else {
        // The answered word goes up or down; every other drilled word only decays a little.
        const cls = !answered ? "decay" : w.confidence > before.confidence ? "up" : "down";
        conf.append(el("span", ` (${pct(before.confidence)} → ${pct(w.confidence)})`, cls));
      }
    }
    const right = Boolean(w.last_correct);
    const since = right ? `${w.gap} (×${w.answer_decay.toFixed(2)})` : w.attempts ? "never right" : "never drilled";
    tr.append(
      el("td", w.hangul), el("td", w.english), conf, el("td", w.attempts ? pct(w.accuracy) : "-"),
      el("td", right ? `×${w.time_decay.toFixed(2)}` : "-"), el("td", since),
      el("td", `${w.streak}`), el("td", right ? `${w.half_life}d / ${w.half_life * d.answers_per_day} answers` : "-"),
    );
    table.append(tr);
  }
  const pickNote = debugMode === "words"
    ? `Highlighted: the next word is picked at random from these (the ${d.top_k} least confident, not counting the word on screen; ties included).`
    : `Highlighted: the next generated sentence's ${d.focus_count} focus words are picked at random from these (your weakest words). Each learned word in a graded sentence gets its own right or wrong.`;
  $("debug").replaceChildren(
    el("h2", "Debug"),
    el("p", "confidence = accuracy × time decay × answer decay. Accuracy = (correct + 1) / (attempts + 2). " +
      "Both decays count from your last correct answer and halve once per half-life: " +
      `1 day or ${d.answers_per_day} answers after a miss, doubling with each correct answer in a row. ` +
      "So a wrong answer can only lower confidence, and a word never answered right is 0%.", "muted"),
    el("p", pickNote + " Bold: the word just answered. Light red: decay from other answers.", "muted"),
    d.words.length ? table : el("p", "No learned words in this scope yet.", "muted"),
    d.words.length > rows.length ? el("p", `${d.words.length - rows.length} more words (see Stats).`, "muted") : el("span"),
  );
  lastSeen = Object.fromEntries(d.words.map((w) => [w.id, { confidence: w.confidence, attempts: w.attempts }]));
}
