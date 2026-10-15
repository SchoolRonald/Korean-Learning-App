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
