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
