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

Load a file:

```
.venv/bin/python -m app.loader data/unit1.csv
```

The loader prints the CSV's columns. If they don't match the defaults (`Korean`, `English`, `Lesson`), pass the names:

```
.venv/bin/python -m app.loader data/unit1.csv --hangul "Hangul" --english "Meaning" --lesson-col "Lesson"
```

If the file has no lesson column, give one lesson number for the whole file with `--lesson 5`.
Reloading a file is safe; duplicate words are skipped.

To try the app without the purchased lists, load the made-up sample in `sample/basic_words.csv` (40 beginner words, lessons 1 to 4):

```
.venv/bin/python -m app.loader sample/basic_words.csv
```

Delete `gongbu.db` to start over before loading the real lists.

The database path defaults to `gongbu.db` and can be changed with the `GONGBU_DB` env var.

## Run

```
.venv/bin/uvicorn app.main:app --reload
```

Open http://localhost:8000 for the spelling drill. Pick the highest lesson you have studied, type the Korean for the English prompt, and press Enter (Enter again or Next for the next word).

## Stats

http://localhost:8000/stats shows your weakest words (highest fail rate), the words you haven't seen in the longest time, and every word sorted by **confidence**: an estimate of how likely you are to spell it right now. Confidence = accuracy x memory, where accuracy is (correct + 1) / (attempts + 2) and memory halves every *half-life* days since you last saw the word. The half-life starts at 1 day after a miss and doubles with each correct answer in a row, up to 64 days. Only spelling-drill answers count. The spelling drill uses the same score: it picks randomly from the 5 least confident words (never-practiced words first).

## Sentence mode (AI)

http://localhost:8000/sentences shows a short English sentence built from words at or below your lesson (favoring your weakest words). Type the Korean translation.

- Needs an Anthropic API key. Copy `.env.example` to `.env` (gitignored) and set `ANTHROPIC_API_KEY`, then restart the server. A real environment variable overrides `.env`. Uses `claude-haiku-5-5`.
- An answer that exactly matches the reference translation (ignoring spaces and punctuation) is marked correct without an AI call. Anything else is graded by the AI, and that grading is **not validated**. Compare with the reference yourself.
- AI calls are capped per server run (default 50, set `GONGBU_LLM_CAP`). Restart the server to reset. Token usage is printed and appended to `llm_usage.log`.
- Generated sentences are saved in the database and reused before new ones are generated.

## Tests

```
.venv/bin/pytest -q
```
