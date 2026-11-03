# Spec: Gongbu, an adaptive Korean learning tool

## Overview

Gongbu teaches Korean vocabulary and grammar, following the lesson order of howtostudykorean.com (HTSK). A learner first learns to read and type Hangul. Then the learner learns words and grammar points a few at a time, drills them, practices them in AI-generated sentences, and tracks progress. The app adapts in two ways:

1. It scores how well each word and grammar point is remembered (its **confidence**) and drills the weakest first.
2. It explains grammar in the style that works for the learner, and it learns that style from what the learner does.

The site has six tabs, in this order in every page's menu:

| Tab | URL | Purpose |
|---|---|---|
| Basics and Introduction | `/basics` | Read and type Hangul: alphabet, keyboard, letter quiz |
| Learn Words | `/` | Introduce new words, 5 at a time |
| Learn Grammar | `/grammar` | Learn and review grammar points with adaptive explanations and practice |
| Words | `/words` | Spelling drill on learned words |
| Sentences | `/sentences` | Translate AI-generated sentences built from learned words and grammar |
| Stats | `/stats` | Progress and confidence for learned words and grammar |

Stack: Python, FastAPI, SQLite (no ORM), one static HTML/JS page per tab (no build step), Anthropic API (`claude-haiku-5-5`) for Sentences, topics and grammar, and the NIKL Basic Korean Dictionary API (krdict) as the grammar source.

## Shared parts

### Word data

- Word lists are purchased CSVs from howtostudykorean.com, copyrighted, so they live in `data/` (gitignored) and each user downloads their own.
- `python -m app.loader <csv>` loads a list into the `words` table (`hangul`, `english`, `lesson`). The "Simple List" files have no header row: Korean, English, and a lesson tag like `Unit1_Lesson25`. The lesson is the last number in the tag, since lessons are numbered across units. Columns can be given by number (no header) or by name (header row). Reloading a file inserts nothing new.
- Some Korean cells hold notes. Every tab accepts each listed form: `아기 / 애기` (either), `1월 (일월)` (numeral or spelled out), `평생 (동안)` (optional extra word), `옛 _____` (blank), `어때?` (punctuation ignored).

### Scope: lesson and topic

Learn Words, Learn Grammar, Words, Sentences and Stats share a scope selector at the top of the page:

- **Up to lesson N**: only words and grammar points from lessons 1 to N. Remembered per browser.
- **Topic (optional)**: the learner types a topic in their own words ("food", "days of the week") and presses Apply. One AI call picks the matching words at or below lesson N, so a beginner never gets advanced words. The result is saved per (topic, lesson), so using it again is free. The page shows how the AI read the topic, the word count, "picked by AI, not validated", and a Clear button. With a topic, every tab uses only that topic's words. A topic does not filter grammar points. API: `POST /api/topics {name, lesson}`; the other endpoints take an optional `topic` id.
  - The AI copies the chosen lines (`커피 = coffee`) and the server matches them to the list by text, keeping only words really in scope. (Numeric ids were tried first and the AI often wrote the wrong ones.)

### Learned words

A word becomes **learned** by finishing it in the Learn Words tab or by "I already know this word". Words, Sentences and Stats use learned words only. Learned words are stored in the `learned` table.

### Confidence and word selection

Confidence estimates the chance (0 to 100%) that the learner can spell a word right now:

- confidence = accuracy × time decay × answer decay
- **Accuracy** = (correct + 1) / (attempts + 2), so one lucky answer is not certainty (1/1 is 67%, 10/10 is 92%).
- Both decays count from the **last correct answer**. Time decay halves every half-life in days; answer decay halves every half-life × 10 drill answers since then (to any word, including misses of this one), so forgetting also shows within one session.
- The half-life is 1 after a miss and doubles with each correct answer in a row, up to 64 (64 days, 640 answers).
- A word never answered correctly is 0%. A wrong answer can never raise confidence and a right answer can never lower it.
- Words-drill answers count. Sentence answers also count, with one verdict for each word (see Tab 5). Learn Words results do not count.
- Answer decay counts Words-drill answers and Sentence answers. One Sentence answer counts as one answer, not one per word.

Grammar points have their own confidence with the same formula. See Tab 3.

The Words drill picks the next word at random from the 5 least confident learned words in scope (never the word just answered, unless it is the only one). Unpracticed words are 0%, so newly learned words come up first.

### AI usage

- Model `claude-haiku-5-5`, low effort for sentences and grading, medium for topics (resolved once and saved). Every call asks for JSON with a fixed schema; malformed output, refusals and API errors become a friendly message, never a crash.
- At most 500 AI calls per server run (`GONGBU_LLM_CAP`). Restart the server to reset. Each call's duration and tokens are logged to the console and `llm_usage.log`.
- The API key comes from `ANTHROPIC_API_KEY` (or `.env`).

### AI call counter

With Debug on, every page shows a small, muted counter in the bottom-left corner: "AI calls: N / 500". N is the number of AI calls in this server run. It updates after each action that can make an AI call. API: `GET /api/usage` returns `{calls, cap}`.

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

## Tab 2: Learn Words (`/`)

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
- Learn Words results do not change confidence. A newly learned word starts at 0%, so the Words tab brings it up first.

### API

`GET /api/learn/batch?lesson&topic`, `POST /api/learn/check {word_id, step: english|cloze, answer, index}`, `POST /api/learn/done {word_id}`.

### Acceptance criteria

- With nothing learned, Words says to learn some first; after finishing a batch, those words appear in Words.
- Every one of the 1030 Unit 1 entries accepts its own English text, and its bracketed notes written out; a wrong answer ("dog") is rejected.
- "I already know this word" marks the word learned immediately.
- Finishing a batch sends its "done" requests at once without server errors.

## Tab 3: Learn Grammar (`/grammar`)

### Goal

Grammar is the hardest part of Korean for an English speaker. Textbooks explain each point one way only. If that way does not work for the learner, the learner has no other path. Many apps give no explanation at all: they show a sentence and its translation and expect the learner to find the rule.

This tab teaches each grammar point with an explanation that adapts to the learner, many examples, and practice that shows how the point is used and where its nuance is.

### Grammar data

The grammar data has three layers. Each layer is saved, so the app does not generate the same content again.

1. **Curriculum** (`grammar/curriculum.json`, committed):
   - The grammar point names and their lesson numbers come from the public HTSK lesson list (https://www.howtostudykorean.com/other-stuff/lesson-list/). Point names and order are facts. The app copies no HTSK lesson text.
   - The first curriculum covers only the lessons in the loaded word CSVs. Today that is Unit 1, Lessons 1 to 25.
   - The lesson topics are typed into `grammar/htsk_lessons.json` (committed), one entry per lesson.
   - Some lessons hold several points (Lesson 12: 들, 만, 에서, 부터, 까지, (으)로). For each lesson, the build makes two AI calls:
     1. **Split**: the lesson becomes points. For each point the AI also names the exact krdict headwords to look up, with their part of speech (`은` particle, `-아요` ending, `-고 싶다` pattern).
     2. **Summarize**: the AI gets each point's candidate krdict entries. It keeps only the entries that really are the point (the same spelling can be a different word: 이 is "this" and also "two"), and writes the summary from them.
   - Each point has: `id` (a slug, for example `particle-eseo`), `lesson`, `title`, `pattern` (for example `N + 에서`), `kind` (`particle`, `ending`, `conjugation`, `expression` or `usage`), `summary` (the core rule in one or two sentences), `related` (ids of similar points to compare), `lookups` (the krdict headwords searched, so `--refresh` can redo sources and summaries without a new split), and `sources`.
   - Some lessons are about usage more than grammar (Lesson 10: numbers and counters, Lesson 21: question words). They become points of kind `usage`.
2. **Sources** (`grammar/sources.json`, committed):
   - For each point, the build saves the chosen entries from the NIKL Basic Korean Dictionary (krdict): definitions, English translations, usage notes, up to 3 Korean examples per sense, and the entry URL. The file also holds the attribution and license.
   - krdict content is CC BY-SA 2.0 KR. Every page that shows krdict content shows "Source: NIKL Basic Korean Dictionary (CC BY-SA 2.0 KR)" with a link to the entry.
   - A point with no krdict entry (for example "word order") is marked `sources: []`. Its AI content is then grounded only on the curriculum summary, and the page says so.
3. **Generated content** (database, created on first use):
   - Explanations, examples and practice items. See below.

Build command: `python -m app.curriculum --lessons 1-25`. It needs `ANTHROPIC_API_KEY` and `KRDICT_API_KEY` (both in `.env`). It is run once by the developer, and the two JSON files are committed. Running it again keeps existing points and adds only missing lessons.

The krdict API: `https://krdict.korean.go.kr/api/search` and `/api/view`, XML responses, 50,000 calls per day, key from https://krdict.korean.go.kr/eng/openApi/openApiRegister. The app calls krdict only from build steps and the verb-class lookup, never on each page load.

### Learned and in-scope points

- A point is **in scope** when its lesson is at or below the scope lesson N.
- A point becomes **learned** when the learner finishes it in "Learn new" or presses "I already know this". Learned points are stored in the `grammar_learned` table.
- New points come in curriculum order (lesson, then position in the lesson).

### Explanation styles

Every explanation uses one of these styles:

| Style | What it does |
|---|---|
| Examples first (default) | Many examples (at least 8) from simple to harder, with the grammar part highlighted. The rule comes after the examples. |
| Compare with English | Starts from how English says the same thing and shows where Korean is different. |
| Rule and table | States the rule, then a table of forms (after a vowel, after a consonant, irregulars). |
| Break it down | Splits example sentences into their parts (stem, ending, particle) and labels each part. |

Every explanation, in every style, also has:

- At least 8 examples. Each example has the Korean, the English, and the grammar part highlighted.
- A "Nuance" part: when to use the point, when not to, and how it differs from related points.
- A "Common mistakes" part.
- The source line (see Grammar data).
- "AI-written, not validated by a native speaker".

Examples use learned words where possible. They may use at most 2 unlearned words. Unlearned words and names are underlined with a hover hint, the same as on the Sentences tab.

### Adapting the explanation

1. **Explain it differently**: a button under the explanation. It shows the point in the next style the learner has not seen for this point. When the learner has seen all four styles, one AI call writes a new explanation from a different angle.
2. **Ask for a style**: a short text box, "Explain it like...". The learner types a request in their own words ("with food examples", "like I am 10", "compare it to Spanish"). One AI call writes an explanation that follows the request.
3. **Free questions**: a text box, "Ask about this point". The learner asks anything ("why is it 를 here and not 가?"). One AI call answers it. The answer uses the point's summary, its sources and the explanation on screen. Questions and answers stay on the page for this point and are saved.
4. **Learner profile**: the app infers which styles work for the learner (see below). The next new point opens in the best style so far.

The four built-in styles are saved per point after their first generation, so they are free to show again. Explanations from "Ask for a style" and from the fifth and later "Explain it differently" are saved too, so the learner can scroll back to them, but they are not reused for other points.

### Learner profile

The profile is a score for each built-in style. It is stored in the `style_stats` table.

- **Shown**: +1 each time a style is the last explanation the learner reads before the first practice item of a point.
- **Worked**: +1 when that first practice item is answered correctly.
- **Rejected**: +1 when the learner presses "Explain it differently" while that style is on screen.
- Score = (worked + 1) / (shown + 2) − 0.1 × rejected / (shown + 1).
- The style with the highest score opens the next new point. On a tie, Examples first wins.
- A "Default style" menu on the page lets the learner set a fixed style instead of Auto. Auto is the default.
- When the learner uses "Ask for a style", the app saves the request text. After 3 requests, the app adds them as a note to every new explanation prompt ("This learner likes: food examples, ...") and shows the note on the page with a Clear button.

### Practice types

| Type | Task | Checking |
|---|---|---|
| Conjugation | "가다 + past polite" → 갔어요 | Conjugation engine. AI only when the engine cannot decide. |
| Fill the blank | "저___ 학생이에요" → 는 | Deterministic, against the item's accepted answers. |
| Compare | Pick between related points: "저(는/가) 학생이에요" | Deterministic. An item may accept both, and then the feedback explains the difference in meaning. |
| Transform | Change a sentence: present to past, casual to polite, positive to negative | Exact match or engine first, then AI. |
| Translate | English to Korean, using the point | Exact match first, then AI, like Sentences. |
| Spot the error | Find and fix the one grammar error in a sentence | Exact match with the corrected sentence first, then AI. |

- Each answer gets feedback right away: correct, almost, or incorrect, with the right answer and a short reason. The reason names the rule ("after a consonant, use 은").
- AI makes practice items in batches of 5 per point and type, and saves them in the `grammar_items` table with their accepted answers. When the learner has seen every saved item of a type for a point, the next batch is made.
- Items use learned words where possible, with at most 2 unlearned words, underlined as in explanations.
- A point uses only the types that fit it. Compare needs related points. Conjugation needs a point of kind `conjugation` or `ending`.

### Conjugation engine

A deterministic engine conjugates verbs and adjectives. It does not need AI for most answers.

- It covers the endings in Lessons 1 to 25: present polite (아요/어요), past (았/었어요), future (ㄹ/을 거예요), formal (ㅂ니다/습니다), honorific (으세요, 으셨어요), negation (안 + verb, 지 않아요), ~고, ~고 싶어요, ~고 있어요, adjective modifier (ㄴ/은), and 아/어지다.
- It handles the classes: regular, 하다, 이다/아니다, ㄷ, ㅂ, ㅅ, ㅎ, 르, 으, and ㄹ.
- It accepts every valid form, including contractions (되어요 and 돼요, 보아요 and 봐요).
- **Verb classes**: the spelling of a verb does not show its class (입다 is regular, but 돕다 is ㅂ-irregular). The app finds the class from the conjugated forms in krdict and saves it in the `verb_classes` table. When krdict has no entry, one AI call tags the class, and the class is marked "AI-tagged".
- When the engine cannot decide (unknown class, or a form it does not cover), the answer goes to AI grading.

### Learn new

1. The page shows the next unlearned point in scope. Title, pattern and lesson are at the top.
2. The explanation opens in the profile's best style (see Learner profile).
3. The learner reads it and may use "Explain it differently", "Explain it like..." and "Ask about this point" as often as they like.
4. "Practice" starts 4 practice items of the types that fit the point. Fill the blank or Conjugation come first, and Translate comes last.
5. A miss shows the answer and the reason, and puts the item type back at the end, as in Learn Words. The explanation stays one click away.
6. After the items, the point is learned. The page shows "Next point" and "Review".
7. "I already know this" (at any step) marks the point learned at once and moves to the next point.

### Point list

- Under the page, a collapsible list shows every point in scope with ✓ for learned points.
- Clicking a point opens it at `/grammar?point=<id>`, learned or not. Stats links to points the same way.
- A learned point shows "✓ Learned" in place of the finish buttons.

### Review

- A "Review" mode on the same page. It shows practice items for learned points in scope, weakest point first.
- It picks the next point at random from the 3 least confident learned points, never the point just answered unless it is the only one.
- Each item comes from a random type that fits the point.
- After an answer, "Show explanation" opens the saved explanation for that point.

### Mixed review in Learn new

- Between points (after one point is learned and before the next one opens), the page shows 1 or 2 review items when any learned point is below 50% confidence.
- Review never appears inside a point's explanation or its practice.
- A **Focus** checkbox (remembered per browser, off by default) turns mixed review off.

### Grammar confidence

- Same formula as word confidence: accuracy × time decay × answer decay, from the last correct answer.
- Answer decay counts grammar answers only: Review answers, Learn new practice answers, and Sentence grammar verdicts.
- All practice answers count, including AI-graded ones. "Almost" counts as a miss.
- An "ungraded" answer (AI failed) is not recorded.

### Debug panel (Learn Grammar)

With Debug on, the page shows:

- Every learned point in scope, least confident first, with the same columns as the word Debug panel.
- The style scores (shown, worked, rejected, score) and the style that opens next.

### Rules

- Grammar points are not filtered by topic.
- Every AI output on this tab is labeled "AI-written, not validated by a native speaker".
- AI calls follow Shared parts: AI usage. Explanations, items and answers are JSON with a fixed schema.

### API

- `GET /api/grammar/next?lesson` returns the next unlearned point (or null) and the outline of points in scope. The page then asks for the explanation separately, because a new explanation can take up to a minute.
- `GET /api/grammar/point?id&lesson` returns one point, the outline, and its saved custom explanations.
- `GET /api/grammar/explain?point&lesson&style` returns the saved explanation in that style, or makes it.
- `POST /api/grammar/explain {point, lesson, request}` makes an explanation from a free style request. An empty request makes one from a new angle.
- `POST /api/grammar/ask {point, lesson, question, explanation_id}` answers a free question about the explanation on screen.
- `GET /api/grammar/item?point&type` returns a practice item. Without `point`, it returns a review item.
- `POST /api/grammar/answer {item_id, answer}` checks an answer and records it.
- `POST /api/grammar/done {point}` marks a point learned.
- `GET /api/grammar/profile` and `POST /api/grammar/profile {default_style}` read and set the profile.

### Acceptance criteria

- `grammar/curriculum.json` has points for every lesson from 1 to 25. Every point has all fields, and every `related` id exists.
- Every point with sources shows the source line and a working krdict link.
- The first point opens in Examples first with at least 8 examples.
- "Explain it differently" shows the 4 styles in turn, and showing a saved style again makes no AI call.
- "Ask about this point" answers and keeps the answer on the page after a reload.
- The conjugation engine gives the right forms for a fixed test list that covers every class and every listed ending, including both contracted and full forms.
- 저가 for "저___ 학생이에요" (expected 는) is marked wrong with a reason. A Compare item that accepts both forms marks both correct.
- After an answer, the point's confidence changes by the same rules as a word: a wrong answer never raises it, and a right answer never lowers it.
- With Focus on, no review item appears in Learn new.
- With a style answered correctly more often, new points open in that style.

## Tab 4: Words (`/words`)

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

## Tab 5: Sentences (`/sentences`)

### Goal

Practice learned words and learned grammar in context: translate a short English sentence into Korean. This tab is also the main place where grammar is practiced in real use.

### What the page shows

- An English sentence built from the learner's learned words and learned grammar points. Words that need a Korean word the learner has not learned, and names, are underlined; hover or click shows the Korean ("호텔 = hotel (new word)", "민호 = Minho (name)"). A line says how many words are not learned yet.
- The learner types the Korean and presses Enter. The reference translation appears at once; the AI explanation follows about a second later. Every word in the reference shows its meaning on hover or click.
- Grading is labeled: "Graded by exact match with the reference" or "Graded by AI (unvalidated). Compare with the reference yourself."
- After grading, the grammar points the sentence uses, each with ✓ or ✗ and a link to its explanation.
- The AI call count ("AI calls: N / 500") and the Debug panel.

### Rules

- Needs at least 5 learned words in scope (and, with a topic, at least one learned topic word), and every grammar point of Lesson 1 learned. Otherwise the page says what is missing and points to Learn Words or Learn Grammar.
- **Generation** (one AI call): the vocabulary is the learned words at or below the lesson (newest first, up to 2000); 3 focus words are sampled from the 8 weakest (from the topic, if one is set); the 20 most recent sentences are listed to avoid repeats. The AI returns the English, the Korean, and one token per Korean word (form, dictionary form, meaning, matching English words, whether it is a name).
- **Grammar in generation**: the prompt lists the learned grammar points in scope (id, title, pattern) and says to use only these. One focus point is sampled from the 3 least confident learned points. The AI returns the ids of the points the sentence uses. The server rejects a sentence that lists an unknown or unlearned point, or does not use the focus point. This check trusts the AI's list, so it is labeled unvalidated like the rest of generation.
- Saved sentences from before this change have no grammar list. They are not served.
- The server checks the tokens against the list: the list's meaning replaces the AI's; an attached copula is stripped (뭐예요 → 뭐); for a spelling with several entries (저: "I" or "that"), the AI's meaning picks the entry; a list word can never be called a name. A sentence is rejected if it uses no learned word, more than 2 unlearned words (names do not count), no topic word (with a topic), or repeats a saved sentence.
- **Caching**: sentences are saved. A saved sentence not yet attempted is served first; while the learner answers, the next one is generated in the background, so "New sentence" is usually instant. If generation fails, the least recently practiced saved sentence is reused. "New word" flags are recomputed each time, so hints disappear as words are learned.
- **Grading**: an exact match with the reference (spacing and punctuation ignored), or with the reference with 그/저-type words swapped when they mean "that/there", is correct with no AI call. Otherwise one AI call returns correct, almost or incorrect with a reason; either 그- or 저- forms are accepted unless the English says which. If grading fails, the answer is "ungraded" and not recorded.
- **Verdicts per word and point**: grading also returns a verdict for each learned word in the reference and each grammar point the sentence uses: correct or wrong.
  - An exact match makes every verdict correct with no AI call.
  - With AI grading, a word is correct when the answer uses it or another valid translation of the same meaning. This is why verdicts are per word: one English word can have several right Korean words.
  - Unlearned words and names get no verdict.
- Word verdicts change word confidence. Grammar verdicts change grammar confidence. An "ungraded" answer changes nothing.

### API

`GET /api/sentence?lesson&topic&exclude`, `POST /api/sentence/answer {sentence_id, answer}`.

### Acceptance criteria

- A sentence is only generated from learned words, with at most 2 unlearned words, each underlined with its Korean on hover.
- Names are labeled as names, not new words, and are never added to the word list.
- In "This tree is in Korea.", the hint for "is" underlines the word "is", not the "is" in "This".
- Malformed AI output, refusals, a missing API key and API errors show a message instead of an error page.
- With Lesson 1 grammar not learned, the page points to Learn Grammar.
- A sentence lists only learned grammar points, and always includes the focus point.
- A wrong word in an otherwise right answer lowers only that word's confidence.

## Tab 6: Stats (`/stats`)

### Goal

Show progress for words and grammar in the current scope and explain how confidence works.

### What the page shows

- Summary: "Learned X of Y words, practiced Z. Average confidence of learned words N%."
- **Weakest words**: the 10 learned words with the highest fail rate (words with at least one miss), with fails/attempts and confidence.
- **Not seen in a while**: the 10 practiced words seen longest ago.
- **All learned words by confidence** (collapsible): lesson, attempts, streak, confidence bar.
- **Grammar**: "Learned X of Y grammar points. Average confidence N%." Then the 5 weakest points, and all learned points by confidence (collapsible), each linking to its explanation.
- **How you learn best**: the style scores in plain words ("Examples first works best for you: 8 of 10 first answers right").
- **About confidence**: the formula and rules in plain words (see Shared parts).

### API

`GET /api/stats?lesson&topic`.

### Acceptance criteria

- Counts and lists cover only words in scope; lists cover only learned words.
- A word with no misses never appears under Weakest words.
- Grammar counts and lists cover only points in scope.

## Out of scope (whole app)

Accounts and login, audio, deployment, an error taxonomy, a "this looks wrong" button for AI output, and styling beyond readable. AI output (sentences, grading, topic word lists, grammar explanations and items) is labeled as unvalidated rather than checked by a person. Review of AI output by native speakers happens outside the app. Grammar for lessons beyond the loaded word lists is not built.

## Build order

The grammar feature is built in steps. Each step ends with passing tests and a working page, so the learner can test it before the next step starts.

1. **Data**: krdict client, `python -m app.curriculum`, `grammar/curriculum.json` and `grammar/sources.json` for Lessons 1 to 25, tests on both files, and the AI cap of 500.
2. **Learn Grammar, explain**: the tab, menu changes (Learn becomes Learn Words), Learn new with the four styles, "Explain it differently", "Explain it like...", "Ask about this point", "I already know this", and the Debug call counter.
3. **Practice and confidence**: Fill the blank, Compare, Translate, and Spot the error, the item bank, grammar confidence, Review mode, mixed review, Focus, and the grammar Debug panel.
4. **Conjugation engine**: verb classes from krdict, the engine with its test list, and the Conjugation and Transform types.
5. **Learner profile**: style scores, Auto style choice, Default style menu, and saved style requests.
6. **Sentences and Stats**: grammar in generation, the Lesson 1 minimum, per-word and per-point verdicts, confidence updates from Sentences, and the Stats grammar sections.

## Points to review

These are choices the learner did not make. Each one has a default in this spec.

1. Profile score: the formula and the 0.1 weight for "Rejected".
2. Practice length in Learn new: 4 items per point.
3. Mixed review: 1 or 2 items, only when a learned point is below 50%.
4. Review picks from the 3 least confident points. Words picks from 5.
5. "Almost" counts as a miss for grammar confidence.
6. Sentences minimum: 5 learned words and all Lesson 1 points.
7. One Sentence answer counts as one answer for word answer decay.
8. Saved sentences from before this change are not served.
9. Style requests become a profile note after 3 requests.

