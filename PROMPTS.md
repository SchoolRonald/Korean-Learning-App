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

## Extra: sentence mode latency (and duplicate sentences)

**Prompt:** "some of the sentences sometime take a second to generate, and when submitting an answer (that's incorrect) you sometimes wait a few seconds for the response on why you're wrong."

**What was done:**
- Measured first instead of guessing, with real calls on a copy of the database (5 per setting). Generate: median 0.89s with adaptive thinking vs 0.91s with thinking off. Grade: 1.39s vs 1.30s. So turning thinking off was not the fix; each call simply takes about 1 to 1.5s, with rare spikes when the model decides to think (one logged call had 676 output tokens).
- **Prefetch:** after `GET /api/sentence` responds, a FastAPI background task generates one more sentence if fewer than 2 unattempted ones are waiting. A lock makes a request wait for an in-flight prefetch instead of paying for a second call. Measured: the next-sentence request went from about 1s to about 3ms.
- **Reference shown instantly:** `GET /api/sentence` now includes the reference, and the page shows it the moment you press Check. The AI reason fills in about 1.5s later. Trade-off: the reference is in the page data before you answer (visible in dev tools), and a failed grade can no longer be retried, since the reference is already on screen. It is shown as not recorded.
- **Logging:** each call's duration is now in `llm_usage.log`. The call counter is now locked, since the prefetch thread and a request can call at the same time.

**Issues and fixes:**
- Found during the real test: the prefetched sentence was identical to the one on screen. The real database had 13 saved sentences but only 9 distinct ones, so this predated prefetch. The model got nearly the same prompt every time (same vocab, same top 3 focus words). Fixed three ways: focus words are now sampled at random from the 8 weakest, the prompt lists the 20 most recent sentences to avoid, and a sentence whose English already exists is not saved.
- The avoid-list made Haiku think more: 4 of 5 generations took 3 to 5s (400 to 830 output tokens). With thinking off they took 1.1 to 2.3s, but 3 of 5 sentences used words outside the vocab list (앉다, 손, 씻다) vs 1 of 5 with thinking on (그녀). Kept thinking on, since prefetch hides generation time and sticking to known words matters more. Small sample, not a rigorous comparison.
- Page race found while editing: clicking New sentence while a grade is in flight would let the late result overwrite the new sentence's feedback. The page now ignores results for a sentence that is no longer shown.
- Bug of mine: the new "prefetch skipped" log line used the real logger, so a test run wrote one line into the real `llm_usage.log`. Removed that line and routed the message through the logger the tests replace.
- Test fixes: the API flow test needed extra fake replies for the background prefetches. A sampling test built the focus pool twice, but ties between unseen words are random, so it now uses a fixed pool.
- Noticed, not fixed: with only 40 sample words, some sentences are nonsense ("The chair is a desk.") and the model sometimes uses words outside the list. The code drops unknown words from `words_used`, but it cannot detect an unknown word inside the Korean itself.

## Extra: remove duplicate sentences

**Prompt:** "yeah delete the duplicates."

**What was done:** One-off cleanup of the local database (no code change). Backed up `gongbu.db` to `gongbu.backup.db`. For each English sentence saved more than once, kept the oldest copy, moved the attempts from the other copies onto it, and deleted the rest: 13 sentences became 9, all distinct, with all 5 sentence attempts kept and none left pointing at a deleted sentence.

**Issues and fixes:** None. Moved the attempts before deleting, since 3 of the 4 removed copies had answer history.

## Extra: loading the real CSV

**Prompt:** "also i have the real csv. i just placed it in the project root for now."

**What was found** (inspected before changing the loader, as the spec asked): `Unit 1 Simple List.csv`, 1030 rows, always 3 columns, **no header row**: Korean, English (quoted when it has commas), and a lesson tag like `Unit1_Lesson25`. 25 lessons of 30 to 54 words. Data-quality issues that would have broken the drill:
- 18 Korean cells hold notes, not a single word: `1월 (일월)`, `평생 (동안)`, `냄새 (나다)`, `아기 / 애기`, `옛 _____`, `어때?`.
- 36 entries contain spaces (`관심이 있다`).
- 48 English prompts map to more than one Korean word (teacher: 교사, 선생님). Already handled by the same-English rule.
- 22 Korean words have more than one meaning (차: car, tea). These are separate rows, which is fine.

**What was generated:**
- Moved the CSV into `data/` (gitignored, as the spec requires).
- Loader: a mapping can now hold column numbers (headerless file) or column names (header row). The default is `{hangul: 0, english: 1, lesson: 2}`, matching the real lists. `parse_lesson` now uses the *last* number. The first number would have made every `Unit1_LessonN` word lesson 1, and the lesson numbers continue across units. The CLI accepts numbers or names. Removed the header from `sample/basic_words.csv` so it has the same layout.
- Checker: `answer_variants()` turns a cell into its accepted answers (either side of `/`; an optional word in brackets; a numeral or its spelled-out reading; blanks and end punctuation removed). `check_entry()` accepts any form, ignores spacing (correct, with a note "Usually written 관심이 있다"), and gives syllable feedback against the closest form.
- Sentence mode: the vocab limit went from 500 to 2000, newest lessons first (500 would have dropped lessons 13 to 25 at lesson 25), and the model's `words_used` is matched against every accepted form.
- Database: renamed the old `gongbu.db` (sample words plus test history) to `gongbu.sample.db` instead of deleting it, and loaded the real list into a fresh `gongbu.db`: 1030 words, lessons 1 to 25. Reloading inserts 0.
- Tests: 101 passing. Added loader tests for the real format, lesson tags, column ranges, and mixed mappings; tests for each annotation pattern and for spacing; and a sentence test for annotated entries.

**Issues and fixes:**
- First version of `answer_variants` also accepted `1월 일월` (numeral plus reading together). Removed after printing the variants for all 18 annotated entries from the real file.
- First version of `check_entry` had a convoluted note-handling branch. Rewritten as three plain steps: exact, spacing-insensitive, closest wrong.
- Measured on the real data: a lesson-25 sentence sends about 10k input tokens. That is about 3.2s per call (hidden by prefetch) and about $0.001 per call.

## New features, phase 1: Learn tab and learned-only practice

**Prompt:** Pasted feature ideas: a Learn tab first (monkeytype-style typing over the word a few times, then Korean-to-English, then fill in a removed syllable); practice only on words seen in Learn, with hover meanings for unseen words in sentences; study by user-chosen category. Clarified with three questions: topics are made on the spot by the AI and capped by lesson level; the English step is typed with lenient matching; hints go both on the English prompt and on the Korean reference. Planned in 3 phases. This entry is phase 1.

**What was generated:**
- `learned` table. `word_stats()` in `app/memory.py` now has a `learned` flag, and `in_scope(words, topic_ids, learned_only)` is the one place where scope is filtered. The scheduler drills learned words only (404 "Learn some first" otherwise). Stats counts "Learned X of Y" and lists learned words only. Sentence focus words are learned only.
- `app/learn.py`: `batch()` (next 5 unlearned words in list order, each with its first accepted form and a random one-syllable cloze for words of 2 or more syllables), `english_ok()` (lenient matcher), `cloze_check()` (reuses the jamo checker; typing the whole word also counts), `mark_learned()`.
- API: `GET /api/learn/batch`, `POST /api/learn/check`, `POST /api/learn/done`. `/` is now the Learn page, and the drill moved to `/words` (`static/index.html` renamed to `words.html`). The nav on every page is Learn | Words | Sentences | Stats.
- `static/learn.html`: a batch runs step by step across all 5 words (type over x3, then English, then cloze), which spaces out the repetition. Type-over colors each syllable green or red but leaves the syllable still being composed by the IME uncolored, since it is often half built. A rep finishes on a match (ignoring spaces) once the IME has committed, so press space or Enter. Misses in steps 2 and 3 show the answer and requeue the word with no penalty. At the end the words are marked learned.
- Tests: `tests/test_learn.py` (matcher cases taken from the real list's formats, cloze, batch order and scope, API flow and bad input). Learned-only and topic-scope tests in the scheduler. Existing fixtures now mark their words learned. 130 passing.

**Issues and fixes:**
- 14 existing tests failed after the learned-only change, as expected, because their fixtures had never "learned" any words. Fixed the fixtures rather than the code.
- Checked the matcher against all 1030 real entries: 167 entries rejected their own English text (e.g. typing "I, me" for "I, me (formal)"), because the answer was not split like the meanings. Now an answer is split the same way and accepted when every part matches; 0 rejected. Rejects "I, dog".
- Designed around an IME double-advance: Enter during composition fires both `compositionend` (which can complete a rep) and the deferred Enter handler. Enter in the type-over step only re-checks, never advances, and completion is guarded by a flag.
- Known leniency: the typo allowance accepts "interested" for "to be interested in" (ratio 0.87). Left as is; it is a learning step, not a test.
- Not tested in a real browser with a Korean IME. The JS parses (`node --check`), and the API flow was smoke-tested on a running server against a copy of the database.

## Extra: gray text to type over

**Prompt:** "i would prefer, when typing the word for the first time with the word as reference and when you're typing the word with a missing character, there's like a gray text in the textbox that you're actually writing over."

**What was generated:**
- In the type-over and fill-in steps, the input's own text is transparent (the caret stays visible), and a layer behind it (`#ghost`) draws the typed text followed by the rest of the target in gray. The typed part is the same text in the same font, so it lines up with the input exactly. Type-over colors typed syllables green or red (the syllable being composed stays uncolored), and the big word above stays as a plain reference. Fill-in shows `한_` in gray and you type the whole word over it, uncolored so the blank is not given away.
- `cloze_check()` now treats a whole-word answer as a whole-word check, so feedback points at the syllable in the word ("Syllable 2: expected 생, you typed 샹"). A single syllable is still accepted.

**Issues and fixes:**
- Alignment risks fixed before testing: the body's `line-height: 1.5` applied to the overlay but not the input, and the inline input left a gap under it. Both elements now share font, size, line-height, padding and border, and the input is `display: block`.
- Checked in Chrome on a throwaway server: screenshots kept timing out, so I measured with JS instead. Same box, same font and line-height, text start within 0.01px, typed-text width within 0.02px, and typing 남차 over 남자 marked 남 green and 차 red. Not tested with a real Korean IME.
- Repeated an old mistake: `pkill -f` matched its own shell command again while stopping the throwaway server (see step 1). No harm; cleaned up separately.

## Bug: 500 errors when finishing a Learn batch

**Prompt:** Server log showing `POST /api/learn/done` returning 500 (`sqlite3.InterfaceError: bad parameter or other API misuse`) twice, plus one 404, at the end of a Learn batch.

**Cause (my bug, since step 1):** `app/main.py` used one global sqlite3 connection, opened with `check_same_thread=False`. FastAPI runs sync endpoints on a thread pool, and the Learn page sends its 5 "done" requests at once, so several threads used the same connection at the same time. sqlite3 connections are not safe for that, hence the InterfaceError. The 404 was the same race: a lookup on a word that exists read back nothing. The background sentence prefetch had the same latent problem, because it was handed the request's connection and ran on another thread.

**Fix:**
- `db()` in `app/main.py` gives each thread its own connection, cached per thread and per database path. Every endpoint uses it. The background prefetch now opens its connection inside its own thread (`prefetch_in_background`). SQLite handles several connections to one file; Python's default 5s busy timeout covers write contention.
- Reproduced first: `tests/test_concurrency.py` fires 150 "done" requests from 10 threads. It failed 3 of 3 runs with the same InterfaceError before the fix and passed 10 of 10 after.
- Test fixtures that go through the API now use a temporary database file instead of `:memory:` (an in-memory database is private to one connection) and commit their setup data. The app is pointed at it via `main.db_path`.

**Data:** in the real database 2 of the 5 words in that batch were saved (남자, 그). The other 3 (여자, 이, 저) were never marked learned, so they come first in the next batch. No cleanup needed.

## New features, phase 2: sentences from learned words, with hints

**Prompt:** "start phase 2"

**What was generated:**
- Generation uses only learned words at or below the lesson as its vocabulary (at least 5 needed; otherwise a 404 that points to the Learn tab). The prompt allows at most 2 words outside the list, and asks for a sensible sentence.
- `words_used` is replaced by `tokens`: one entry per space-separated Korean word, with its form in the sentence, dictionary form, meaning, and the words it translates in the English. The server matches each token against every accepted form of every word. When it finds the word, the **list's** meaning replaces the model's, and the token is new if that word is not learned. A sentence's `word_ids` holds only its learned words (used for the lesson filter). Sentences with more than 2 new words are rejected.
- "New" is recomputed each time a sentence is served, so hints disappear as you learn the words. Saved sentences are filtered the same way. Sentences saved before this phase have no tokens, so they are only used once all their words are learned.
- Tokens are stored only when they spell out the sentence (spaces and punctuation ignored). Otherwise the sentence is kept with no hints.
- `init_db` now adds missing columns (`sentences.tokens`) to an existing database.
- `static/sentences.html`: in the English prompt, the words that need an unlearned Korean word are underlined, and hover (title) or click shows "고양이 = cat (new word)". After answering, every Korean word in the reference has its meaning on hover or click. All built with `textContent`.
- Tests: tokens and learned ids, unlearned words not offered, too many new words, tokens that do not spell the sentence, new flags following learning, old sentences without tokens, same-spelling words, the migration, not-ready (and its 404). 140 passing.

**Issues and fixes:**
- Bug found in a real run on a copy of the database: in "이것은 저 것이에요", 저 meant "that (over there)", but the hint said "I, me (formal)". The list has both 저 entries, the user had learned both, and the code took the first learned one. Now the model's meaning for that token picks the entry (using the Learn tab's lenient English matcher), with the first learned entry as a fallback.
- Two test mistakes of mine: one "too many new words" sentence had no learned words at all, so it was rejected as unusable first; one test inserted into `learned` without OR IGNORE after the fixture had already filled it.
- Real runs (12 learned words, lesson 1): sentences like "That man is Korean. / 그 남자는 한국 사람이에요." with 사람 flagged as new. Generation now takes 3 to 8 seconds (the model thinks more with a small vocabulary); the background prefetch hides that after the first sentence. The 5 older saved sentences are skipped until their words are learned.
- Checked in Chrome on a throwaway server: the prompt underline, hover text and count line, and the reference spans all render. Stopped the server by PID this time rather than `pkill -f`.

## Extra: accept either 그 or 저 for "that"/"there" in sentences

**Prompt:** "for these sentences with 그 and 저, it should really be either or based on whatever the user types. both should be correct for "there". either that, or the sentence question should specify "there (close to other person)" and "there (far)""

**What was generated** (chose "accept either", since English "that"/"there" really does not say near the listener or far from both):
- Deterministic: `reference_variants()` builds the reference plus every version with its demonstratives swapped word by word (그/저, 거기/저기, 그것/저것, 그거/저거, 그곳/저곳, 그쪽/저쪽, including shortened forms like 저건/그건). An exact match on any version is correct with no AI call, with the note "그 and 저 are both fine". A token is only swapped when its meaning says "that/those/there", so 저 as "I" (저는) and 그 as "he" are never swapped. Uses the stored tokens; sentences without tokens fall back to the grader.
- AI grader: the instructions now say to accept either 그- or 저- forms unless the English sentence says which.
- The Words drill needed no change: its prompts come from the list, which already distinguishes "that" from "that (when something is far away)".
- Tests: 6 variant cases (including the "I" and "he" non-swaps and two demonstratives in one sentence), grading 그 against a 저 reference with no AI call, and the grader instruction. 148 passing.

**Issues and fixes:** My first version swapped by string replacement and hit the wrong 그 when it appeared twice ("저건 그 책이에요" produced a duplicate and missed "그건 저 책이에요"). Caught by spot-checking before writing tests; now swaps by word position using the tokens.

## Bug: "that thing" rejected for "that (thing)" in Learn

**Prompt:** "in the learn section, when writing the meaning of a word in english, i feel like something like this is stupid: Not quite. You'll see this one again. 저것 means: that (thing) (my answer was "that thing")"

**Cause (my design):** the lenient matcher threw bracketed notes away, so for "that (thing)" the only accepted answer was "that". Writing the note out as part of the meaning was treated as wrong.

**Fix:** each meaning is now accepted both without its note and with the note as plain words: "that (thing)" accepts "that" and "that thing"; "Korean (language)" accepts "Korean language"; "(the color) black" accepts "black" and "the color black". Apostrophes are dropped before comparing, so the list's "mother’s" (curly) matches a typed "mother's". Checked against all 1030 real entries: every entry accepts its own text and its notes written out, and a wrong answer ("dog") is still rejected. 5 new test cases, 153 passing.

## Bug: names treated as new words in sentences

**Prompt:** "in sentences: This man's name is Minho. 민호 = is Minho (new word). "minho" isn't a word, it's a name. just in case its listed as a word or something, it shouldnt go into the user's dictionary (like there shouldnt be a confidence score associated with minho)"

**Checked first:** words from sentences never enter the `words` table or `stats`; only rows from the CSV can be learned, drilled, or scored. The real database has no 민호 or 민수 in `words`, and no stats row without a word. The CSV's capitalized entries are countries, languages, days, months, and directions, which are real vocabulary. So nothing needed removing; the problem was only how sentences labeled names.

**What was generated:**
- The generation schema has a required `is_name` per token, and the model is told to give just the name as its meaning ("Minho", not "is Minho"). Widened to names of places too after finding "서울 = is Seoul (new word)" in a saved sentence.
- Name tokens are not new words: they don't count toward the 2-unlearned-word limit or the "N words you have not learned" line. They are still underlined in the prompt (you need the Hangul spelling) with the label "민호 = Minho (name)" in their own color.
- A token that matches a word in the list is never a name, so the model cannot call a real word a name to get around the limit.
- Tokens saved before this change default to "not a name". Fixed the two affected saved sentences in the real database (#8 서울, #13 민호) after backing it up to `gongbu.backup.db`.
- Tests: name not new and not added to `words`, names not counted toward the limit, a list word cannot be a name, old tokens without the flag. 157 passing. Real run: "My name is Jiyeon. / 제 이름은 지연이에요." marked 지연 as a name.

## Bug: "뭐예요 = what is" instead of "뭐 = what"

**Prompt:** "What is that name? 뭐예요 = what is (new word). here, the translation of what shouldn't be "워예요", it should just be "뭐""

**Cause:** the model left the copula attached when giving the dictionary form (뭐 + 예요 "is"), so the token did not match the list's 뭐 and the model's own "what is" was shown. Same pattern as the earlier "민호 = is Minho".

**Fix:**
- When a token's base is not in the list and ends in the copula (이에요, 예요, 입니다, 이야), the copula is stripped and the stem looked up again; "is/am/are" is trimmed from the model's meaning and English span to match. 뭐 is in the list (lesson 22, "what"), so the hint now reads "뭐 = what (new word)" from the list. A list word that happens to end like the copula (e.g. 아니에요) is matched first and never stripped.
- The prompt now tells the model to leave the copula off the base (뭐예요 -> 뭐).
- Fixed the one affected saved sentence (#15) in the real database after a backup.
- Tests: copula stripped with the list match, copula stripped for a word not in the list, a list word ending in 이에요 kept. 160 passing. (One test failed at first because its new word was not marked learned, so the sentence had no learned words; a test mistake, not a code bug.)

## New features, phase 3: AI topics

**Prompt:** "start phase 3" (Plan: you type a topic in your own words; the AI picks matching words, capped at the selected lesson so the words stay at your level; every tab uses the topic.)

**What was generated:**
- `topics` table and `app/topics.py`: `resolve(conn, name, lesson)` normalizes the name and returns the saved topic for (name, lesson) if there is one. Otherwise it makes one AI call with every word at or below the lesson, keeps only words really in the list, and saves the result, even an empty one, so asking again is free. Returns a friendly 404 for no matches or a bad name.
- API: `POST /api/topics`, and an optional `topic` id on `/api/learn/batch`, `/api/next`, `/api/sentence` (and its prefetch), and `/api/stats`. An unknown id is a 404.
- Sentences with a topic: focus words come from the topic's learned words, the rest of the learned vocabulary stays available for grammar, a new sentence must use a topic word, and saved sentences are only served for the topic if they contain one. Needs at least one learned topic word ("Learn some words from this topic first").
- `common.js`: `initScope()` adds the topic box (input, Apply, status with the AI's reading of the topic, word count, "picked by AI, not validated", and Clear) to all four pages, which now share one scope (`scopeQuery()`). The topic name is remembered in localStorage and re-resolved on page load and lesson change (free when already saved).
- `call_json` takes an optional effort level.
- Tests: `tests/test_topics.py` (scope filtering, caching per topic and lesson, saved empty results, bad output, bad names, topic scope in learn, stats and sentences, the API). 173 passing.

**Issues and fixes:**
- Real test of the first version: "food" included 학교 (school), 꼬리 (tail), 공 (ball), 바지 (pants), 트럭 (truck), and "transportation" included 가수 (singer), 퍼센트 (percent), 아프다 (to be sick). The model was picking words by numeric id and often writing the wrong ids. Fixed by having it copy the chosen lines exactly ("커피 = coffee") and mapping the text back to the word (each Korean/English pair is unique). Topics also now use medium effort, since each is resolved once and saved. After the fix the lists were on topic, and homographs were handled: 배 (pear) in food, 배 (boat) in transportation. "Food" at lesson 5 gave 16 early-lesson words; at lesson 25, 49 words including 라면 and 젓가락. Topic lookups now take 3 to 8 seconds, once.
- Checked in Chrome on a throwaway server: applying "food" at lesson 5 showed 15 words and a food-word Learn batch, the topic carried over to Stats from the saved result (exactly one AI call in total), and Clear restored all words.

## Bug: Words drill rejected 저 for "that"

**Prompt:** "in words currently, there is a bug with the "there" thing again: that / 저 / Not quite. Answer: 그"

**Cause (my mistake):** when fixing 그/저 for sentences I said the Words drill needed no change because the list distinguishes them. Only half true: the 저 card says "that (when something is far away)", but the 그 card just says "that", and 저 is an equally good answer to a plain "that". The same-English rule did not catch it because the two cards' English differs.

**Fix:** the 그/저 pair table moved to `app/checker.py` (shared with sentences). `demonstrative_partner()` returns the other word only when the card's English is a plain "that/those/there" without a distance word (far, farther, near, close). So:
- 그 "that" accepts 저, and 거기 "there" accepts 저기, with the note "Also correct: both 그 and 저 mean "that". 그 is near the listener, 저 is far from both of you."
- 저 "that (when something is far away)" and 저기 "there (when farther away)" still require 저/저기, since the card says which.
- 그 "he, him" and 저 "I, me (formal)" are never swapped.
- 그것/저것 ("that (thing)") and 그쪽/저쪽 ("that direction") already worked, since their English is identical.

Tests use the real list's entries (6 cases plus the note). 180 passing. Checked against the real database (read-only): "that" + 저 and "there" + 저기 are now correct; "that (when something is far away)" + 그 is still wrong, with syllable feedback.

## Extra: "I already know this word" in Learn

**Prompt:** "in the learning section, can we also add an override button for "i already know this word" which will skip the process of learning the word and allows the user to instantly use them in words or sentences"

**What was generated:** a button in `static/learn.html`, available during any step. It marks the word learned at once (the existing `POST /api/learn/done`, so no server change), drops it from every remaining step of the batch, and shows "Marked as known: ..." on the page. If every word in the batch is marked known, the next batch loads. The finished screen lists "Already knew: ..." separately from "Learned: ...". A skipped word starts at 0% confidence like any new word, so the Words drill brings it up soon and checks that it really is known.

**Issues and fixes:** designed around one race: in the type-over step a finished rep advances on a 250ms timer, so skipping during that window would have advanced twice. The button is ignored while that timer is pending. Checked in Chrome on a throwaway server: skipping the first word removed it from the queue and showed the next one, skipping the other four loaded a new batch, and all five were saved as learned.

## Bug: hint underlined "is" inside "This"

**Prompt:** "This tree is in Korea. 있다 = to be at a location (new word) but the wrong "is" is highlighed. it highlights "Th*is* tree is in Korea". Not "This tree *is* in Korea""

**Cause (my bug):** `renderPrompt` found each token's English text with a plain `indexOf`, so "is" matched inside "This".

**Fix:** new `findPhrase()` in `static/sentences.html` returns the first case-insensitive occurrence that is a whole word or phrase (no letter or digit right before or after, Unicode-aware) and does not overlap text already underlined. Checked with 7 cases run in node: "is" in "This tree is in Korea." (now position 10), an "is" already taken, a capitalized "Is", "his" vs "is", a name, a multi-word phrase, and "at" inside "cat sat" (no match).
