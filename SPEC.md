# Spec: Gongbu, an adaptive Korean learning tool

## Overview

Gongbu teaches Korean vocabulary from the howtostudykorean.com word lists. A learner first learns to read and type Hangul, then learns words a few at a time, drills their spelling, practices them in AI-generated sentences, and tracks progress. The app adapts by scoring how well each word is remembered (its **confidence**) and drilling the weakest words first.

The site has five tabs, in this order in every page's menu:

| Tab | URL | Purpose |
|---|---|---|
| Basics and Introduction | `/basics` | Read and type Hangul: alphabet, keyboard, letter quiz |
| Learn | `/` | Introduce new words, 5 at a time |
| Words | `/words` | Spelling drill on learned words |
| Sentences | `/sentences` | Translate AI-generated sentences built from learned words |
| Stats | `/stats` | Progress and confidence for learned words |

Stack: Python, FastAPI, SQLite (no ORM), one static HTML/JS page per tab (no build step), Anthropic API (`claude-haiku-5-5`) for the Sentences tab and topics.

## Shared parts

### Word data

- Word lists are purchased CSVs from howtostudykorean.com, copyrighted, so they live in `data/` (gitignored) and each user downloads their own.
- `python -m app.loader <csv>` loads a list into the `words` table (`hangul`, `english`, `lesson`). The "Simple List" files have no header row: Korean, English, and a lesson tag like `Unit1_Lesson25`. The lesson is the last number in the tag, since lessons are numbered across units. Columns can be given by number (no header) or by name (header row). Reloading a file inserts nothing new.
- Some Korean cells hold notes. Every tab accepts each listed form: `아기 / 애기` (either), `1월 (일월)` (numeral or spelled out), `평생 (동안)` (optional extra word), `옛 _____` (blank), `어때?` (punctuation ignored).

### Scope: lesson and topic

Learn, Words, Sentences and Stats share a scope selector at the top of the page:

- **Up to lesson N**: only words from lessons 1 to N. Remembered per browser.
- **Topic (optional)**: the learner types a topic in their own words ("food", "days of the week") and presses Apply. One AI call picks the matching words at or below lesson N, so a beginner never gets advanced words. The result is saved per (topic, lesson), so using it again is free. The page shows how the AI read the topic, the word count, "picked by AI, not validated", and a Clear button. With a topic, every tab uses only that topic's words. API: `POST /api/topics {name, lesson}`; the other endpoints take an optional `topic` id.
  - The AI copies the chosen lines (`커피 = coffee`) and the server matches them to the list by text, keeping only words really in scope. (Numeric ids were tried first and the AI often wrote the wrong ones.)

### Learned words

A word becomes **learned** by finishing it in the Learn tab or by "I already know this word". Words, Sentences and Stats use learned words only. Learned words are stored in the `learned` table.

### Confidence and word selection

Confidence estimates the chance (0 to 100%) that the learner can spell a word right now:

- confidence = accuracy × time decay × answer decay
- **Accuracy** = (correct + 1) / (attempts + 2), so one lucky answer is not certainty (1/1 is 67%, 10/10 is 92%).
- Both decays count from the **last correct answer**. Time decay halves every half-life in days; answer decay halves every half-life × 10 drill answers since then (to any word, including misses of this one), so forgetting also shows within one session.
- The half-life is 1 after a miss and doubles with each correct answer in a row, up to 64 (64 days, 640 answers).
- A word never answered correctly is 0%. A wrong answer can never raise confidence and a right answer can never lower it.
- Only Words-drill answers count. Sentence answers are graded by AI and not validated, so they do not change confidence.

The Words drill picks the next word at random from the 5 least confident learned words in scope (never the word just answered, unless it is the only one). Unpracticed words are 0%, so newly learned words come up first.

### AI usage

- Model `claude-haiku-5-5`, low effort for sentences and grading, medium for topics (resolved once and saved). Every call asks for JSON with a fixed schema; malformed output, refusals and API errors become a friendly message, never a crash.
- At most 50 AI calls per server run (`GONGBU_LLM_CAP`); restart the server to reset. Each call's duration and tokens are logged to the console and `llm_usage.log`.
- The API key comes from `ANTHROPIC_API_KEY` (or `.env`).

### Debug panel (Words and Sentences)

For demos: a **Debug** checkbox in the menu (remembered per browser, off by default) shows every learned word in scope, least confident first, with confidence, accuracy, time decay, answers since last right (and that decay), streak and half-life. After each answer the word just answered is bold with its before and after confidence; other words' small decay is light red. Highlighted rows are where the next pick comes from: on Words, the next-word pool; on Sentences, the weak words the next sentence's focus words are drawn from. API: `GET /api/debug?lesson&topic&exclude`.

### Typing Korean

Every Korean answer box handles the Korean input method: pressing Enter while the last syllable is still being composed waits for it to finish, so the whole answer is submitted.

## Tab 1: Basics and Introduction (`/basics`)

### Goal

The other tabs assume you can already read Hangul and type it on a Korean keyboard. This tab teaches both, for a complete beginner: the Korean alphabet, the Korean 2-set (두벌식) keyboard layout, how to turn Korean typing on, and a short letter quiz. It does not use the scope selector.

### What the page shows

1. **Turn on Korean typing**
   - Windows: Settings → Time & language → Language & region → Add a language → Korean. Switch keyboards with Win+Space.
   - Mac: System Settings → Keyboard → Input Sources → Edit → + → Korean → 2-Set Korean. Switch with Ctrl+Space.
   - How syllables are built: letters stack into blocks. ㅎ + ㅏ + ㄴ = 한, typed as G K S.
2. **Alphabet chart**: 40 letters in 4 groups:
   - 14 basic consonants
   - 5 double consonants
   - 10 basic vowels
   - 11 combined vowels

   Each card shows the letter, its romanization, its name, and an example word with its English meaning. Clicking a card lights up the key(s) that type it on the keyboard below. A letter that takes two key presses (for example ㅘ = H then K) shows the steps numbered 1 and 2.
3. **Keyboard**: a drawn QWERTY keyboard with each key's Korean letter, its Shift letter (ㅃ ㅉ ㄸ ㄲ ㅆ ㅒ ㅖ), and the English key letter.
   - All keys are the same width. Rows are staggered like a real keyboard: the A row starts a quarter key right of Q, the Z row (after a Shift key) three quarters, so the top row, ending in ㅔ, reaches furthest right.
   - While Shift is held anywhere on the page, keys with a Shift letter show it large (ㅐ → ㅒ, ㅔ → ㅖ, ㄱ → ㄲ ...) with the plain letter in the corner, and the Shift key is highlighted. It switches back when Shift is released or the window loses focus.
4. **Practice box**: as you type in it, each key you press lights up on the keyboard.
   - With the Korean keyboard on, browsers report key presses as "Process", so the keys are worked out from the typed text: the most recent letter of the last character (한 → ㄴ, 하 → ㅏ, 닭 → ㄱ, 와 → ㅗ then ㅏ numbered).
   - With English typing, keys light up by the physical key, and the page tells you to switch to the Korean keyboard.
5. **Letter quiz**: 10 random letters, in one of two modes:
   - **See letter, type it**: the page shows ㄱ, you type ㄱ.
   - **See sound, type the letter**: the page shows "g/k", you type ㄱ.

   - You answer each question with Enter. The page then shows ✓ or ✗ right away. A ✗ says the correct letter, its sound and its key(s), and lights up those keys. Enter again (or Next) goes to the next question.
   - A vowel typed with the silent ㅇ in front (아 for ㅏ) counts as correct. The page also adds a note that 아 is ㅏ with the silent ㅇ, so both count, and that the letter on its own is ㅏ.
   - An answer in English letters does not count. The page shows the "switch to Korean" hint instead and lets you try again.
   - After the 10th question the page shows your score and a review in two lists: "✗ To review" (shown first) and "✓ Correct". Each row shows what was asked, your answer, the correct letter and its key(s). Clicking a row lights up its keys on the keyboard.
   - "Try again" starts a new quiz.

### Letter data

All letter and keyboard data is in `static/hangul.json`, so it lives in one place and the tests can check it.

- `letters`: groups, each `{name, letters: [...]}`. Each letter is `{char, name, roman, example: {word, english}, keys}`.
  - `name` is the Korean name plus its romanization, e.g. `기역 (giyeok)`.
  - `roman` is unique across all 40 letters, so the sound quiz has one right answer. The strong (aspirated) consonants are marked, e.g. ㅋ is `k (strong)`, while ㄱ is `g/k`.
  - `keys` is the key presses that type the letter, using browser key codes: `["KeyR"]` for ㄱ, `["Shift+KeyR"]` for ㄲ, `["KeyH", "KeyK"]` for ㅘ.
- `keyboard`: 3 rows of keys, each `{code, latin, char, shift}` (`shift` is null when Shift gives no new letter).

### Out of scope

- No database tables and no server API: the page is static and runs in the browser.
- Quiz results are not saved and do not appear on the Stats tab.
- No AI calls.
- Example words are a fixed list, not taken from the loaded vocab.

### Acceptance criteria

- `/basics` loads, and every tab's menu links to it as the first item.
- Clicking ㄱ lights up R. Clicking ㅘ lights up H (1) and K (2). Clicking ㄲ lights up R and Shift.
- With the Korean keyboard on, typing in the practice box lights up each key pressed (typing 한국 lights ㅎ, ㅏ, ㄴ, ㄱ, ㅜ, ㄱ in turn).
- All keys are the same width, and the top row ends further right than the other two.
- Holding Shift shows ㅃ ㅉ ㄸ ㄲ ㅆ ㅒ ㅖ on their keys; releasing it shows the plain letters again.
- Both quiz modes run 10 questions. Each answer shows ✓ or ✗ before moving on, and the quiz ends with the ✗/✓ review lists.
- Answering 아 for ㅏ shows ✓ plus the silent-ㅇ note.
- Typing English letters in the quiz or practice box shows the switch hint.
- `pytest` passes, including tests that check `hangul.json`: 40 unique letters (14/5/10/11), every field present, every key exists on the keyboard, single-key letters match their key, and romanizations are unique.

## Tab 2: Learn (`/`)

### Goal

Introduce new words before they are drilled, so practice only ever uses words the learner has seen. This is the home page.

### What the page shows

- The next 5 unlearned words in scope, in list order (lesson, then list position).
- Each batch runs step by step across all 5 words, which spaces out the repetition:
  1. **Type it over** (3 times per word): the word is shown large with its meaning, and the answer box shows it in gray; the learner types over the gray text, monkeytype-style. Typed syllables turn green or red; the syllable still being composed by the input method stays uncolored. A repetition finishes on a match (spacing ignored) after space or Enter.
  2. **Korean to English**: the word is shown; the learner types its meaning.
  3. **Fill the blank** (words of 2 or more syllables): the word is shown with one random syllable missing (`한_`), in gray in the answer box; the learner types the whole word over it (or just the missing syllable). Not colored while typing, so the blank is not given away.
- A miss in steps 2 or 3 shows the answer and puts the word back at the end of that step. No penalty.
- **I already know this word** (any step): marks the word learned at once and drops it from the rest of the batch. If the whole batch is skipped, the next batch loads.
- At the end: "Learned: ...", "Already knew: ...", "Learn 5 more", and a link to practice in Words. When every word in scope is learned, the page says so.

### Rules

- The English check is lenient: case, a/an/the, punctuation and apostrophe style are ignored; a meaning is accepted without a leading "to " or "to be " ("big" for "to be big"); bracketed notes may be left out or written out ("that" or "that thing" for "that (thing)"); several meanings may be listed if each is right ("I, me"); a small typo is allowed for answers of 4+ letters.
- Learn results do not change confidence. A newly learned word starts at 0%, so the Words tab brings it up first.

### API

`GET /api/learn/batch?lesson&topic`, `POST /api/learn/check {word_id, step: english|cloze, answer, index}`, `POST /api/learn/done {word_id}`.

### Acceptance criteria

- With nothing learned, Words says to learn some first; after finishing a batch, those words appear in Words.
- Every one of the 1030 Unit 1 entries accepts its own English text, and its bracketed notes written out; a wrong answer ("dog") is rejected.
- "I already know this word" marks the word learned immediately.
- Finishing a batch sends its "done" requests at once without server errors.

## Tab 3: Words (`/words`)

### Goal

Drill the spelling of learned words, weakest first, with feedback precise enough to show which part of a syllable was wrong.

### What the page shows

- An English prompt; the learner types the Korean and presses Enter (Enter again or Next for the next word).
- Feedback: correct or not, the answer with wrong syllables underlined, and per-syllable messages naming the wrong part ("Syllable 2: expected 생, you typed 샹 (vowel wrong)"), missing or extra syllables, and a hint if the answer has English letters.
- The Debug panel (see Shared parts).

### Rules

- Checking is deterministic: answers are compared in Unicode NFD and aligned syllable by syllable, so one missing syllable does not shift the rest.
- Accepted as correct: any listed form of the entry; different spacing (with a note on the usual spacing); another word in the list with the same English meaning (with a note naming the card's word); for a card meaning plain "that" or "there", the other demonstrative (그 or 저, 거기 or 저기), with a note on near and far. A card that says which (저: "that (when something is far away)") requires that word.
- Each answer is recorded (`attempts`, `stats`) and updates confidence. The next word is never the one just answered.

### API

`GET /api/next?lesson&topic&exclude`, `POST /api/answer {word_id, answer}`.

### Acceptance criteria

- Only learned words in scope are asked.
- 선샹님 for 선생님 says syllable 2's vowel is wrong; 고이 for 고양이 says 양 is missing.
- 일월 is accepted for "January"; 저 is accepted for 그 "that" but 그 is not accepted for 저 "that (when something is far away)".
- A wrong answer never raises the word's confidence; a right one never lowers it.

## Tab 4: Sentences (`/sentences`)

### Goal

Practice learned words in context: translate a short English sentence into Korean.

### What the page shows

- An English sentence built from the learner's learned words. Words that need a Korean word the learner has not learned, and names, are underlined; hover or click shows the Korean ("호텔 = hotel (new word)", "민호 = Minho (name)"). A line says how many words are not learned yet.
- The learner types the Korean and presses Enter. The reference translation appears at once; the AI explanation follows about a second later. Every word in the reference shows its meaning on hover or click.
- Grading is labeled: "Graded by exact match with the reference" or "Graded by AI (unvalidated). Compare with the reference yourself."
- The AI call count ("AI calls: N / 50") and the Debug panel.

### Rules

- Needs at least 5 learned words in scope (and, with a topic, at least one learned topic word); otherwise the page points to the Learn tab.
- **Generation** (one AI call): the vocabulary is the learned words at or below the lesson (newest first, up to 2000); 3 focus words are sampled from the 8 weakest (from the topic, if one is set); the 20 most recent sentences are listed to avoid repeats. The AI returns the English, the Korean, and one token per Korean word (form, dictionary form, meaning, matching English words, whether it is a name).
- The server checks the tokens against the list: the list's meaning replaces the AI's; an attached copula is stripped (뭐예요 → 뭐); for a spelling with several entries (저: "I" or "that"), the AI's meaning picks the entry; a list word can never be called a name. A sentence is rejected if it uses no learned word, more than 2 unlearned words (names do not count), no topic word (with a topic), or repeats a saved sentence.
- **Caching**: sentences are saved. A saved sentence not yet attempted is served first; while the learner answers, the next one is generated in the background, so "New sentence" is usually instant. If generation fails, the least recently practiced saved sentence is reused. "New word" flags are recomputed each time, so hints disappear as words are learned.
- **Grading**: an exact match with the reference (spacing and punctuation ignored), or with the reference with 그/저-type words swapped when they mean "that/there", is correct with no AI call. Otherwise one AI call returns correct, almost or incorrect with a reason; either 그- or 저- forms are accepted unless the English says which. If grading fails, the answer is "ungraded" and not recorded.
- Sentence answers do not change word confidence.

### API

`GET /api/sentence?lesson&topic&exclude`, `POST /api/sentence/answer {sentence_id, answer}`.

### Acceptance criteria

- A sentence is only generated from learned words, with at most 2 unlearned words, each underlined with its Korean on hover.
- Names are labeled as names, not new words, and are never added to the word list.
- In "This tree is in Korea.", the hint for "is" underlines the word "is", not the "is" in "This".
- Malformed AI output, refusals, a missing API key and API errors show a message instead of an error page.

## Tab 5: Stats (`/stats`)

### Goal

Show progress for the current scope and explain how confidence works.

### What the page shows

- Summary: "Learned X of Y words, practiced Z. Average confidence of learned words N%."
- **Weakest words**: the 10 learned words with the highest fail rate (words with at least one miss), with fails/attempts and confidence.
- **Not seen in a while**: the 10 practiced words seen longest ago.
- **All learned words by confidence** (collapsible): lesson, attempts, streak, confidence bar.
- **About confidence**: the formula and rules in plain words (see Shared parts).

### API

`GET /api/stats?lesson&topic`.

### Acceptance criteria

- Counts and lists cover only words in scope; lists cover only learned words.
- A word with no misses never appears under Weakest words.

## Out of scope (whole app)

Accounts and login, audio, deployment, an error taxonomy, a "this looks wrong" button for AI output, and styling beyond readable. AI output (sentences, grading, topic word lists) is labeled as unvalidated rather than checked by a person.
