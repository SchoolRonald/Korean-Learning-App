# Spec: Basics and Introduction tab

## Goal

The other tabs assume you can already read Hangul and type it on a Korean keyboard. This tab teaches both, for a complete beginner: the Korean alphabet, the Korean 2-set (두벌식) keyboard layout, how to turn Korean typing on, and a short letter quiz.

It is the first tab in the menu, at `/basics`. Learn stays at `/`.

## What the page shows

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
4. **Practice box**: as you type in it, each key you press lights up on the keyboard. If you are typing English letters, the page tells you to switch to the Korean keyboard.
5. **Letter quiz**: 10 random letters, in one of two modes:
   - **See letter, type it**: the page shows ㄱ, you type ㄱ.
   - **See sound, type the letter**: the page shows "g/k", you type ㄱ.

   - You answer each question with Enter. The page then shows ✓ or ✗ right away. A ✗ says the correct letter, its sound and its key(s), and lights up those keys. Enter again (or Next) goes to the next question.
   - A vowel typed with the silent ㅇ in front (아 for ㅏ) counts as correct. The page also adds a note that 아 is ㅏ with the silent ㅇ, so both count, and that the letter on its own is ㅏ.
   - An answer in English letters does not count. The page shows the "switch to Korean" hint instead and lets you try again.
   - After the 10th question the page shows your score and a review in two lists: "✗ To review" (shown first) and "✓ Correct". Each row shows what was asked, your answer, the correct letter and its key(s). Clicking a row lights up its keys on the keyboard.
   - "Try again" starts a new quiz.

## Letter data

All letter and keyboard data is in `static/hangul.json`, so it lives in one place and the tests can check it.

- `letters`: groups, each `{name, letters: [...]}`. Each letter is `{char, name, roman, example: {word, english}, keys}`.
  - `name` is the Korean name plus its romanization, e.g. `기역 (giyeok)`.
  - `roman` is unique across all 40 letters, so the sound quiz has one right answer. The strong (aspirated) consonants are marked, e.g. ㅋ is `k (strong)`, while ㄱ is `g/k`.
  - `keys` is the key presses that type the letter, using browser key codes: `["KeyR"]` for ㄱ, `["Shift+KeyR"]` for ㄲ, `["KeyH", "KeyK"]` for ㅘ.
- `keyboard`: 3 rows of keys, each `{code, latin, char, shift}` (`shift` is null when Shift gives no new letter).

## Out of scope

- No database tables and no server API: the page is static and runs in the browser.
- Quiz results are not saved and do not appear on the Stats tab.
- No AI calls.
- Example words are a fixed list, not taken from the loaded vocab.

## Acceptance criteria

- `/basics` loads, and every tab's menu links to it as the first item.
- Clicking ㄱ lights up R. Clicking ㅘ lights up H (1) and K (2). Clicking ㄲ lights up R and Shift.
- With the Korean keyboard on, typing in the practice box lights up each key pressed.
- Both quiz modes run 10 questions. Each answer shows ✓ or ✗ before moving on, and the quiz ends with the ✗/✓ review lists.
- Answering 아 for ㅏ shows ✓ plus the silent-ㅇ note.
- Typing English letters in the quiz or practice box shows the switch hint.
- `pytest` passes, including tests that check `hangul.json`: 40 unique letters (14/5/10/11), every field present, every key exists on the keyboard, single-key letters match their key, and romanizations are unique.
