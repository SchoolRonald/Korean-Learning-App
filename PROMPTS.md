# Prompt Log

## Step 1: Scaffold, schema, CSV loader, loader tests

**Prompt:** Full project spec (stack, data rules, schema, six features in order). "Start with step 1. Show me the CSV columns you find before writing the loader."

**What was generated:**
- `app/db.py`: SQLite connection and schema for `words`, `stats`, `sentences`, `attempts`. Added `UNIQUE(hangul, english)` on `words` so reloading a CSV does not duplicate rows.
- `app/loader.py`: `load_csv(conn, path, mapping, lesson)` with a configurable column mapping, a CLI that prints the detected columns, BOM handling, NFC normalization of Hangul, lesson parsing from text like "Lesson 12", and an optional constant lesson for files without a lesson column.
- `app/main.py`: minimal FastAPI app with `/health` that creates the schema on startup.
- `tests/test_loader.py`: 10 tests (default and custom mapping, constant lesson, lesson text parsing, BOM, blank rows, idempotent reload, missing column, missing lesson value, NFC).
- README, `.gitignore` (ignores `data/` and the db), `requirements.txt`, `pytest.ini`.

**Issues and fixes:**
- No howtostudykorean CSV was available yet, so the real columns could not be inspected. The default mapping (`Korean`, `English`, `Lesson`) is a placeholder; the CLI prints the actual columns so the mapping can be set once the file arrives.
- The CLI originally showed a Python traceback when columns were missing. Changed it to print a one-line error and exit with status 1.
- During manual smoke testing, `pkill -f` matched its own shell command and killed the test script early. Testing issue only, no code change.

## Step 2: Scheduler

**Prompt:** "step 1 looks good, still waiting on csv though." (Spec: given max lesson N, return the next word. Only words with lesson <= N. Score = fail_rate + min(days_since_seen, 14)/14. Unseen words get the max score. Pick randomly from the top 5. Unit test it.)

**What was generated:**
- `app/scheduler.py`: `score()`, `ranked_words()`, and `next_word()`. Unseen words (no stats row, or 0 attempts) score 2.0, the maximum possible, so a seen word can only tie them, never beat them. Timestamps are ISO strings in UTC. `now` and `rng` can be passed in so tests are deterministic.
- `tests/test_scheduler.py`: 10 tests (unseen max score, the score formula, 14-day cap, naive timestamps, lesson filter, empty result, ranking order, picks only from the top 5, ties spread across all words).

**Issues and fixes:**
- Design issue caught before coding: with a fresh database every word is unseen and ties at 2.0. A plain sort would always put the same 5 lowest-id words in the top 5, so the drill would cycle through those 5 until they were seen. Fixed by shuffling before the (stable) sort, so ties break randomly. `test_ties_do_not_always_favor_low_ids` covers it.

## Extra: sample vocab CSV

**Prompt:** "could you just fill out a temp csv with basic (very basic beginner) korean words?"

**What was generated:** `sample/basic_words.csv`, 40 common beginner words written by hand (not taken from howtostudykorean, so it can be committed), 10 per lesson for lessons 1 to 4: people, objects/places, food/animals, and basic verbs/adjectives in dictionary form. It uses the loader's default columns. Added a README note on loading it.

**Issues and fixes:**
- English-to-Hangul drills break when one English prompt has more than one correct Korean answer. Avoided obvious cases: "I" and "you" are marked "(casual)" since 저/당신 are also valid, "fish" is marked "(animal)" since 생선 is fish as food, and 차 was left out because it means both "car" and "tea". The real lists may have the same problem, which matters for step 3.

## Step 3: Spelling drill

**Prompt:** "go ahead with step 3" (Spec: show English, user types Hangul. Check deterministically by normalizing both strings with NFD and comparing per syllable, so feedback can say which syllable was wrong. Record the attempt and update stats. Unit test the checker, including near misses.)

**What was generated:**
- `app/checker.py`: `check(expected, answer)`. Trims whitespace, decides correctness by comparing the NFD forms, lines the syllables up, and splits each wrong syllable into jamo with NFD to report which part was wrong (first consonant, vowel, or final consonant). Returns per-syllable data plus readable feedback lines, and a hint if the answer has Latin letters (the Korean keyboard is probably off).
- `app/drill.py`: `grade_word()` (also accepts another word with the same English meaning, e.g. 저 for "I") and `record_word_attempt()` (adds an `attempts` row and upserts `stats`).
- `app/main.py`: `GET /api/next?lesson=N` returns `{id, english, lesson}` without the Hangul, so the answer is not in the response. `POST /api/answer {word_id, answer}` grades, records, and returns the result.
- `tests/test_checker.py` (13 tests: exact match, NFD input, wrong vowel/first/final consonant, missing batchim, several parts wrong, missing and extra syllables, empty answer, Latin hint) and `tests/test_drill.py` (8 tests: synonyms, stats upsert, API).

**Issues and fixes:**
- Design choice: comparing syllables position by position would shift every later syllable after a single missing one (고이 vs 고양이 would flag 2 syllables instead of 1). The checker aligns the syllables first with `difflib.SequenceMatcher`, then uses NFD only inside each syllable to name the wrong jamo. Correctness is still the NFD comparison from the spec.
- Removed a test comment of mine that claimed 밥/밮 were the "same sound class". It was not needed and you could not easily verify it.

## Step 4: Drill page

**Prompt:** "do step 4" (Spec: lesson selector (N), prompt, input, feedback, next button. Plain HTML/JS calling the API.)

**What was generated:**
- `static/index.html`: one page, no framework. Lesson dropdown (remembered in localStorage), English prompt, answer box, Check and Next buttons, and feedback: correct/wrong, the answer with wrong syllables underlined, per-syllable messages, the synonym note, and the keyboard hint. Shows a session tally. Enter checks the answer, then Enter again (focus moves to Next) loads the next word. Next can also skip a word without recording it.
- `app/main.py`: `GET /` serves the page, `GET /api/lessons` lists the lessons that have words.
- 2 more API tests (43 total).

**Issues and fixes:**
- Korean IME problem handled up front: when typing Hangul, pressing Enter can fire while the last syllable is still being composed, so the answer would be sent without its final syllable (or with a half-built one). The page now notices Enter during composition (`isComposing`, or key code 229) and submits after `compositionend`, once the syllable is committed.
- All server text is inserted with `textContent`, never `innerHTML`, so a CSV entry with HTML in it cannot inject markup.
- Not tested in a real browser by me, since automated typing does not go through a Korean IME. Checked: the JS parses (`node --check`), and the page and API respond on a running server.

## Extra: never repeat the last word

**Prompt:** "let's make it so that the next word is never the same as the word you just answered."

**What was generated:** `next_word(..., exclude=id)` skips the word just shown unless it is the only word available. `GET /api/next` takes `exclude`, and the drill page sends the previous word's id. 3 new tests.

## Step 5: LLM sentence mode

**Prompt:** "but with that, yeah go to step 5" (Spec: generate a short English sentence using only known words (lesson <= N, prefer the weakest words) with a reference Korean translation. User types the Korean. Grade with one LLM call returning JSON `{verdict, reason}`. Cache generated sentences in the `sentences` table. Label grading as unvalidated in the UI. Handle malformed JSON and API errors gracefully. Cap LLM calls per session and log token usage.)

**What was generated:**
- `app/llm.py`: one function, `call_json()`, for all Claude calls. Uses `claude-haiku-5-5` with effort `low` (cheap) and structured output (`output_config.format` with a JSON schema). Enforces a per-server-run call cap (`GONGBU_LLM_CAP`, default 50), logs tokens for each call and running totals to the console and `llm_usage.log`, and turns every failure (no key, bad key, rate limit, network, API error, refusal, malformed or truncated JSON) into an `LLMError` with a message safe to show the user.
- `app/sentences.py`:
  - Generation: sends the known vocabulary (lesson <= N) plus 3 focus words (highest fail rate first, topped up from the scheduler ranking). The model's `words_used` list is checked against the real word list, and words not in it are dropped. If no known word remains, the sentence is rejected.
  - Caching: reuses a saved sentence that has not been attempted and whose words are all <= N. Otherwise it generates a new one. If generation fails, it falls back to the least recently practiced saved sentence.
  - Grading: an exact match with the reference (ignoring spaces and `.,!?`) is "correct" with no AI call. Otherwise one AI call returns `{verdict: correct|almost|incorrect, reason}`. If grading fails, the answer is "ungraded" and is not recorded, so a broken call never counts as a wrong answer.
- `static/sentences.html`: the sentence page, with a yellow "Graded by AI (unvalidated)" label, the reference translation, and the AI call count. `static/common.js` and `static/style.css` hold code and styles shared with the drill page (moved out of `index.html`, including the Korean IME Enter handling).
- `tests/test_sentences.py`: 21 tests using a fake Claude client (no real API calls). They cover generation and word filtering, the cache rules, fallback, exact-match short cut, LLM grading, six kinds of bad grader output, the call cap, usage counting, missing API key, focus words, and the API.

**Issues and fixes:**
- Bug: with no API key, the server crashed with a 500. I had assumed the SDK raises an `AnthropicError` for missing credentials, and my test faked exactly that, so it passed. Running the real server without a key showed that the SDK raises a plain `TypeError` when sending the request. Fixed by checking for credentials when the client is created and raising a friendly `LLMError` (503 "Set ANTHROPIC_API_KEY"). Added a test that uses a client without credentials. Also moved this check before the call counter so a missing key does not use up the cap.
- Bug (UI): when grading failed, the page re-enabled Check but the next line disabled the answer box again. Fixed so an ungraded answer can be retried.
- Design fix: an ungraded response originally included the reference translation, so you could copy it and retry for a free exact match. The server now leaves it out until the answer is graded.
- Test issues: two assertions compared a `sqlite3.Row` to a tuple. The test logger was a child of the app logger, so test runs wrote to the real `llm_usage.log`. Also, `llm_usage.log` was created empty on import (fixed with `delay=True`).
- Considered and rejected: checking that each claimed word appears in the Korean by its stem. Irregular conjugations (하다 to 해요, 보다 to 봐요) would wrongly fail, so the code only checks that claimed words are in the list.
- Not verified: no API key was available while building this, so no real Claude call was made. Prompt quality and how well Haiku follows the "only known words" rule are untested.

## Extra: .env for the API key

**Prompt:** "can we get a .env and a .env.example (obviously putting .env in .gitignore) so i can use my api key?"

**What was generated:** `.env.example` (committed template with `ANTHROPIC_API_KEY`, `GONGBU_LLM_CAP`, `GONGBU_DB`) and `.env` (a copy with the key blank, permissions 600, added to `.gitignore`). Added `python-dotenv`; `app/__init__.py` calls `load_dotenv()` so the server and the loader CLI both read `.env` before any setting is used. Real environment variables still win. README updated.

**Issues and fixes:** None found. Checked that `.env` is loaded and that a blank key still gives the friendly "No Anthropic API key found" error rather than a crash.

## Step 6: Stats page with confidence score

**Prompt:** "lets do step 6. i kind of want to have a "confidence" score, which represents how confident the system thinks that you actually know and remember a word." (Spec: stats page with the 10 weakest words (highest fail rate) and the words not seen in the longest time.)

**What was generated:**
- `app/stats.py`:
  - `confidence(attempts, fails, streak, last_seen, now)` = accuracy x memory. Accuracy is Laplace-smoothed, (correct + 1) / (attempts + 2), so 1/1 is 67% and 10/10 is 92% instead of 100%. Memory is `0.5 ** (days_since / half_life)`, a forgetting curve whose half-life doubles with each consecutive correct answer (1, 2, 4, ... capped at 64 days). Unpracticed words are 0. This is a simplified version of the idea behind spaced-repetition systems: each successful recall makes the memory last longer.
  - `streaks()` reads the `attempts` history to count correct answers in a row per word.
  - `summary()` returns totals, average confidence, the 10 weakest (only words with at least one miss, by fail rate), the 10 least recently seen (practiced words only), and all words sorted by confidence.
- `GET /api/stats?lesson=N` and `static/stats.html`: summary line, two tables with a confidence bar, an "All words by confidence" section, and a plain-language explanation of the formula. Stats link added to all pages.
- `days_since()` factored out of the scheduler so both use the same time calculation.
- `tests/test_stats.py`: 10 tests (smoothing values, half-life decay, fast decay after a miss, cap, streak counting, list contents and order, empty range, API).

**Issues and fixes:**
- Design choices: "weakest" only lists words with at least one miss, since a word with 0% fail rate is not weak. "Not seen in a while" only lists practiced words; never-practiced words are counted in the summary line instead. Stale words are sorted by computed days rather than by the timestamp string so the order does not depend on the timestamp format.
- Confidence uses only spelling-drill answers; sentence verdicts come from unvalidated AI grading, so they are left out.
- The scheduler still uses the formula from the spec, not confidence.
- No bugs found during this step. Checked on a running server with a copy of the database.

## Extra: scheduler uses confidence

**Prompt:** "how does the scheduler algorithm differ from confidence?" then "use confidence then"

**What was generated:**
- Explained the differences: the spec's score added a raw fail rate to a linear, 14-day-capped time term that was the same for every word, and ignored answer order. Confidence multiplies smoothed accuracy by a forgetting curve whose half-life grows with the current streak. Example: a word answered right 20 times and a word answered right once, both last seen 7 days ago, both scored 0.5 under the spec formula, but have about 89% and 6% confidence.
- At the user's request, the scheduler now ranks by priority = 1 - confidence and picks randomly from the top 5. Unpracticed words (confidence 0) still come first. Shuffle-before-sort, the exclude rule, and the top-5 pick are unchanged. **This intentionally replaces the scoring formula given in the original spec.**
- New `app/memory.py` holds `days_since`, `confidence`, `streaks`, and `word_stats`. The scheduler and the stats page both use it, which avoids a circular import (stats needed `days_since` from the scheduler, and the scheduler now needs confidence) and a duplicate query.
- Rewrote `tests/test_scheduler.py`: words now get a real answer history so streaks work. Replaced the 5 tests for the old `score()` with 3 ranking tests (priority = 1 - confidence; a long streak ranks below a single correct answer of the same age; a recent miss resets the streak).

**Issues and fixes:** None found. Note that `streaks()` reads all word attempts on every next-word request. That is fine at prototype size but would need a `streak` column in `stats` for large histories.
