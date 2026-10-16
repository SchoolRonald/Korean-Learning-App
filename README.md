# Gongbu: Adaptive Korean Learning Tool (prototype)

Class project prototype. Drills Korean vocab with a simple spaced-repetition scheduler.

## Setup

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Typing Hangul requires a Korean keyboard/input method enabled in your OS.

## Vocab data

The vocab lists are purchased from howtostudykorean.com and are copyrighted, so they are not in this repo.
Download the CSV for each unit yourself and put them in `data/` (ignored by git).

Load a file (the "Simple List" CSVs have no header row: Korean, English, lesson tag like `Unit1_Lesson25`):

```
.venv/bin/python -m app.loader "data/Unit 1 Simple List.csv"
```

The loader prints the first row. For a CSV laid out differently, give the columns by number (no header row) or by name (header row):

```
.venv/bin/python -m app.loader data/other.csv --hangul Hangul --english Meaning --lesson-col Lesson
```

The lesson is the last number in the lesson column, so `Unit1_Lesson25` is lesson 25.
If the file has no lesson column, give one lesson number for the whole file with `--lesson 5`.
Reloading a file is safe; duplicate words are skipped.

To try the app without the purchased lists, load the made-up sample in `sample/basic_words.csv` (40 beginner words, lessons 1 to 4, same layout as the real lists):

```
.venv/bin/python -m app.loader sample/basic_words.csv
```

Use a separate database for the sample (for example `GONGBU_DB=sample.db`) so it does not mix with the real lists.

The database path defaults to `gongbu.db` and can be changed with the `GONGBU_DB` env var.

## Run

```
.venv/bin/uvicorn app.main:app --reload
```

Tabs:

- **Learn** (http://localhost:8000, start here): introduces new words 5 at a time. Each word: type it over 3 times, type its English meaning, then fill in a missing syllable. Finished words become available in the other tabs. The English check is lenient (case, "to"/"to be", a/the, bracketed notes, and small typos are ignored).
- **Words** (/words): spelling drill on learned words. Pick the highest lesson you have studied, type the Korean for the English prompt, and press Enter (Enter again or Next for the next word).
Spacing does not count against you, and entries with notes accept each listed form: `아기 / 애기` accepts either, `1월 (일월)` accepts `1월` or `일월`, and `평생 (동안)` accepts `평생` or `평생 동안`.

## Topics

Every tab has an optional **Topic** box next to the lesson selector. Type a topic in your own words ("food", "days of the week", "getting around town") and press Apply: the AI picks the matching words at or below your selected lesson, so a beginner never gets advanced words. All tabs then use only that topic's words (Sentences use them as focus words and still allow your other learned words for grammar). Each topic and lesson is resolved once (one AI call, a few seconds) and saved; using it again is free. The word picks are not validated. Clear the topic to go back to all words.

## Stats

http://localhost:8000/stats shows your weakest words (highest fail rate), the words you haven't seen in the longest time, and every word sorted by **confidence**: an estimate of how likely you are to spell it right now. Confidence = accuracy x memory, where accuracy is (correct + 1) / (attempts + 2) and memory halves every *half-life* days since you last saw the word. The half-life starts at 1 day after a miss and doubles with each correct answer in a row, up to 64 days. Only spelling-drill answers count. The spelling drill uses the same score: it picks randomly from the 5 least confident words (never-practiced words first).

## Sentence mode (AI)

http://localhost:8000/sentences shows a short English sentence built from your learned words at or below your lesson (favoring your weakest words). Type the Korean translation. It needs at least 5 learned words. A sentence may use up to 2 words you have not learned: those are underlined in the English (hover or click to see the Korean), and after you answer, every word in the Korean reference shows its meaning on hover or click.

- Needs an Anthropic API key. Copy `.env.example` to `.env` (gitignored) and set `ANTHROPIC_API_KEY`, then restart the server. A real environment variable overrides `.env`. Uses `claude-haiku-5-5`.
- An answer that exactly matches the reference translation (ignoring spaces and punctuation) is marked correct without an AI call. Anything else is graded by the AI, and that grading is **not validated**. Compare with the reference yourself.
- AI calls are capped per server run (default 50, set `GONGBU_LLM_CAP`). Restart the server to reset. Token usage is printed and appended to `llm_usage.log`.
- Generated sentences are saved in the database and reused before new ones are generated. While you answer one sentence, the next is generated in the background, so New sentence is usually instant.

## Tests

```
.venv/bin/pytest -q
```
