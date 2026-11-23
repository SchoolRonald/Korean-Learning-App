# Decisions

This file records decisions that affect the whole project or limit future features and changes. Read it before you change something that crosses tabs. [SPEC.md](SPEC.md) describes what the app does. This file explains why some global choices are the way they are.

## How to add a decision

1. Give the decision the next number.
2. Copy the template below.
3. Fill in each field in short, plain sentences.
4. Do not delete an old decision. If a new decision replaces it, set the old status to "Replaced by D-00N".

```
## D-00N: Short title

- **Date:** YYYY-MM-DD
- **Status:** Accepted

**Context:** The problem, and the facts that matter.

**Decision:** What we do.

**Consequences:** What this changes, and what future work must keep in mind.
```

D-001 to D-010 were written on 2026-11-16 from the project history. Their dates are the dates of the original choice.

## D-001: Small stack with no build step

- **Date:** 2026-10-15
- **Status:** Accepted

**Context:** This is a class prototype for a two-person team. The code must stay small and easy to read.

**Decision:**

1. The server uses Python, FastAPI and SQLite through the standard `sqlite3` module. There is no ORM.
2. Each tab is one static HTML page with plain JavaScript. There is no framework and no build step.
3. Tests use pytest.

**Consequences:**

- Shared page code goes in `static/common.js`, and shared styles go in `static/style.css`.
- All page scripts share one global scope. A name in a page script must not repeat a name in `common.js`. (A duplicate `pct` once broke the Stats page.)
- A schema change needs a migration step in `init_db` for databases that already exist.

## D-002: The word lists stay out of the repository

- **Date:** 2026-10-15
- **Status:** Accepted

**Context:** The vocabulary comes from purchased howtostudykorean.com CSV files. They are copyrighted.

**Decision:**

1. Each user downloads the lists and puts them in `data/`, which git ignores.
2. `python -m app.loader` loads a list into the database. Its column mapping is configurable, so other CSV layouts also work.
3. The lesson number is the last number in the lesson tag (`Unit1_Lesson25` is lesson 25), because lessons are numbered across units.

**Consequences:**

- A new or deleted database has no words until the loader runs.
- Tests use small made-up word lists, never the real files.
- Database files contain the word list, so they must not be committed. Git ignores `*.db`, but it does not ignore backups with other names (for example `.bak`).
- If a later unit restarts its lesson numbers at 1, the loader must combine the unit and lesson numbers.

## D-003: Code checks answers first, and AI output is labeled as not checked

- **Date:** 2026-10-15
- **Status:** Accepted

**Context:** The developers are not fluent in Korean. They cannot check what an AI model writes or how it grades.

**Decision:**

1. Code checks every Korean answer that rules can decide: Unicode normalization, syllable-by-syllable comparison, the listed forms of an entry, spacing, and known equivalents (그 and 저 for "that").
2. An AI model grades only what the rules cannot decide.
3. The page labels all AI output (sentences, grades, topic word lists, grammar lessons and items) as not checked by a person.

**Consequences:**

- A new answer type needs a code check first. AI grading is the fallback, not the default.
- An AI grade must never be shown as if code made it.
- If a grading call fails, the answer is not recorded. A broken call must not count as a wrong answer.

## D-004: The app never trusts ids or claims in AI output

- **Date:** 2026-10-15
- **Status:** Accepted

**Context:** AI models wrote wrong numeric ids (a truck in a "food" topic), left grammar endings on dictionary forms (뭐예요 for 뭐), and called real words names.

**Decision:**

1. When the AI picks words, it copies their text (`커피 = coffee`), and the server matches the text to the word list.
2. The server drops anything that is not in the list or not in the current scope.
3. When a word is in the list, the list's meaning replaces the AI's meaning.
4. A word from the list can never be a name.

**Consequences:**

- New AI features must return text that the server can match to its own data. They must not return ids from the prompt.
- Every AI result goes through a server-side filter before it is saved or shown.

## D-005: Confidence decides what to practice

- **Date:** 2026-10-15
- **Status:** Accepted

**Context:** The first spec used a simple score: fail rate plus days since seen. It treated all words the same and did not use the order of answers. Real use showed two more problems: decay was not visible in one session, and a wrong answer could raise a score.

**Decision:**

1. Confidence = accuracy × time decay × answer decay.
2. Accuracy = (correct + 1) / (attempts + 2).
3. Both decays count from the last correct answer. The half-life is 1 (1 day, 10 answers) after a miss and doubles with each correct answer in a row, up to 64.
4. A word never answered correctly is 0%.
5. The Words drill picks at random from the 5 least confident learned words.
6. Grammar points use the same formula.

History:

- 2026-10-15: confidence replaced the spec's score.
- 2026-11-03: answer decay was added, and both decays changed to count from the last correct answer.
- 2026-11-09: Sentence answers started to count, with one verdict for each word.

**Consequences:**

- A wrong answer must never raise confidence, and a right answer must never lower it. A property test checks this over random histories. Keep it passing when the formula changes.
- The constants are in `app/memory.py`. The Stats page and SPEC.md explain the formula, so update them with any change.

## D-006: Practice uses only learned words

- **Date:** 2026-10-15
- **Status:** Accepted

**Context:** Drilling a word that the learner never saw is not useful.

**Decision:**

1. A word becomes learned in the Learn Words tab, or with "I already know this word".
2. Words, Sentences and Stats use learned words only.
3. A Sentence may use at most 2 unlearned words. Each one has a hint. Names do not count.

**Consequences:**

- A new practice feature must filter by learned words or learned grammar points.
- A newly learned word starts at 0% confidence, so the drill shows it first.

## D-007: The lesson number sets the difficulty

- **Date:** 2026-10-15
- **Status:** Accepted

**Context:** The learner wants to study by topic without seeing advanced words too early.

**Decision:**

1. Every tab with a scope selector uses "Up to lesson N" as its difficulty limit.
2. A topic narrows the words further. It never adds words above lesson N.
3. The topic word list is saved for each (topic, lesson) pair, so a second use makes no AI call.

**Consequences:**

- New content must have a lesson number, or it cannot follow the difficulty limit.
- A topic does not filter grammar points.

## D-008: One database connection for each thread

- **Date:** 2026-10-15
- **Status:** Accepted

**Context:** FastAPI runs requests and background tasks on a pool of threads. One shared SQLite connection caused errors when the Learn page sent several requests at the same time.

**Decision:** `db()` in `app/main.py` gives each thread its own connection.

**Consequences:**

- Never pass a connection to another thread. A background task gets its connection inside its own thread.
- Tests that go through the API use a temporary database file, not `:memory:`, because an in-memory database is private to one connection.

## D-009: Limits and rules for AI calls

- **Date:** 2026-10-15
- **Status:** Accepted

**Context:** AI calls cost money and time, and the model output can be malformed.

**Decision:**

1. Every call asks for JSON with a fixed schema. Malformed output, refusals and API errors become a short message for the learner, never a crash.
2. Each server run has a call limit (`GONGBU_LLM_CAP`, now 500). Each call's time and tokens go to `llm_usage.log`.
3. Results that can be used again are saved and reused: sentences, topics, grammar lessons and items.
4. Slow work runs ahead in the background when possible (for example the next sentence).
5. Tests never call a real API. They use fake clients.
6. Model roles (since 2026-11-09): `claude-sonnet-5-5` does the work that teaches or decides what is correct. `claude-haiku-5-5` does the rest. Jev grades free answers first, and Haiku grades when Jev fails.

**Consequences:**

- A new AI feature must use `call_json` in `app/llm.py`, so it gets the limit, the log and the error handling.
- Ask before you run live API calls for tests or measurement.

## D-010: Responses tell the browser not to reuse old files

- **Date:** 2026-11-09
- **Status:** Accepted

**Context:** After an update, a browser kept an old `common.js`, and the new Learn Grammar page broke.

**Decision:** Every response sends `Cache-Control: no-cache`, so the browser checks with the server before it uses a saved page or script.

**Consequences:** Changes to pages and scripts show after a normal reload. Do not remove this header without a different way to load new files.

## D-011: Design for a desktop window that is half of a 16:9 monitor

- **Date:** 2026-11-16
- **Status:** Accepted

**Context:** The page was 32rem (512 px) wide, so it looked like a mobile layout. The main use is on a desktop. The expected window is half of a 16:9 monitor: on a 1920 × 1080 screen, this is 960 × 1080 px, an 8:9 ratio. After the scrollbar, about 945 px of width is available.

**Decision:**

1. The side margins equal the top margin of the page, 2rem (32 px). The text then has the same space from the left, right and top edges of the window.
2. The content is at most 55rem (880 px) wide. On the target window: 945 px − 2 × 32 px = 881 px, rounded down to whole rem units.
3. On a wider window, the content stays 55rem wide and centered, so text lines stay short enough to read.
4. On a narrower window (for example a scaled laptop display), the content shrinks, and the 2rem margins stay.

**Consequences:**

- New pages and features must fit a 55rem column. Do not add rules that make content wider than the page.
- Elements that scale with the page width can grow too large. Give them their own maximum width. For example, the Basics keyboard is capped at 40rem, so its keys keep a key-like shape.
- The debug panel does not need to be wider than the page.
- The values are in one place: `max-width` and `padding` on `body` in `static/style.css`.
