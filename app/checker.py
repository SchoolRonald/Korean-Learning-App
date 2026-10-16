import difflib
import re
import unicodedata

PART_NAMES = ("first consonant", "vowel", "final consonant")


def normalize(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text or "").strip())


def jamo(syllable):
    """Split a Hangul syllable into (first, vowel, final) jamo, final '' if none. None if not Hangul."""
    if len(syllable) != 1 or not "가" <= syllable <= "힣":
        return None
    d = unicodedata.normalize("NFD", syllable)
    return d[0], d[1], d[2] if len(d) > 2 else ""


def diff_parts(expected, typed):
    a, b = jamo(expected), jamo(typed)
    if a is None or b is None:
        return []
    return [name for name, x, y in zip(PART_NAMES, a, b) if x != y]


def check(expected, answer):
    exp, ans = normalize(expected), normalize(answer)
    syllables = []
    # Align syllables first so one missing or extra syllable does not shift every later one.
    matcher = difflib.SequenceMatcher(None, exp, ans, autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        e_seg, t_seg = exp[i1:i2], ans[j1:j2]
        for k in range(max(len(e_seg), len(t_seg))):
            e = e_seg[k] if k < len(e_seg) else ""
            t = t_seg[k] if k < len(t_seg) else ""
            syllables.append({"expected": e, "typed": t, "ok": op == "equal", "parts": diff_parts(e, t)})
    result = {
        "correct": unicodedata.normalize("NFD", exp) == unicodedata.normalize("NFD", ans),
        "expected": exp,
        "syllables": syllables,
        "feedback": describe(syllables),
    }
    if re.search(r"[A-Za-z]", ans):
        result["hint"] = "Your answer has Latin letters. Is the Korean keyboard on?"
    return result


def describe(syllables):
    lines = []
    for pos, s in enumerate(syllables, start=1):
        if s["ok"]:
            continue
        if not s["typed"]:
            lines.append(f"Syllable {pos}: missing {s['expected']}")
        elif not s["expected"]:
            lines.append(f"Extra {s['typed']} at position {pos}")
        else:
            parts = f" ({', '.join(s['parts'])} wrong)" if s["parts"] else ""
            lines.append(f"Syllable {pos}: expected {s['expected']}, you typed {s['typed']}{parts}")
    return lines


def answer_variants(entry):
    """Accepted answers for a vocab entry. Lists write notes into the Korean cell:
    "아기 / 애기" (either), "평생 (동안)" (optional extra), "1월 (일월)" (numeral or spelled out),
    "옛 _____" (a blank to fill), "어때?" (punctuation).
    """
    variants = []
    for part in entry.split("/"):
        part = re.sub(r"_+", "", part).strip()
        match = re.fullmatch(r"(.*?)\s*\((.+)\)", part)
        if match:
            base, extra = match.group(1).strip(), match.group(2).strip()
            # "1월 (일월)": the brackets spell out the number. Otherwise they hold an optional extra word.
            options = [base, extra] if re.search(r"\d", base) else [base, f"{base} {extra}"]
        else:
            options = [part]
        for option in options:
            option = normalize(option).rstrip("?!.")
            if option and option not in variants:
                variants.append(option)
    return variants or [normalize(entry)]


def loose_match(expected, answer):
    """Same word, ignoring spaces and end punctuation (Korean spacing is often flexible)."""
    def squash(text):
        return re.sub(r"[\s?!.]", "", normalize(text))
    return squash(expected) == squash(answer)


def check_entry(entry, answer):
    """Check an answer against every accepted form of a vocab entry."""
    results = [check(v, answer) for v in answer_variants(entry)]
    for r in results:
        if r["correct"]:
            return r
    for r in results:
        if loose_match(r["expected"], answer):
            return {**check(r["expected"], r["expected"]), "note": f"Correct. Usually written {r['expected']}."}
    # Wrong: give feedback against the closest form.
    return min(results, key=lambda r: sum(not s["ok"] for s in r["syllables"]))
