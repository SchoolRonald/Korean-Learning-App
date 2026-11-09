"""Deterministic conjugation of Korean verbs and adjectives for the endings in Lessons 1 to 25."""

BASE, VOWELS, FINALS = 0xAC00, 21, 28
L_IEUNG, L_RIEUL = 11, 5
V = {"ㅏ": 0, "ㅐ": 1, "ㅑ": 2, "ㅒ": 3, "ㅓ": 4, "ㅔ": 5, "ㅕ": 6, "ㅖ": 7, "ㅗ": 8, "ㅘ": 9, "ㅙ": 10, "ㅚ": 11,
     "ㅛ": 12, "ㅜ": 13, "ㅝ": 14, "ㅞ": 15, "ㅟ": 16, "ㅠ": 17, "ㅡ": 18, "ㅢ": 19, "ㅣ": 20}
T = {"": 0, "ㄴ": 4, "ㄷ": 7, "ㄹ": 8, "ㅂ": 17, "ㅅ": 19, "ㅆ": 20, "ㅎ": 27}
BRIGHT = {V["ㅏ"], V["ㅑ"], V["ㅗ"], V["ㅘ"], V["ㅛ"]}

CLASSES = ["regular", "하다", "아니다", "ㄷ", "ㅂ", "ㅅ", "ㅎ", "르", "으", "ㄹ"]

ENDINGS = {
    "present": "present polite (-아요/-어요)",
    "past": "past polite (-았어요/-었어요)",
    "future": "future (-(으)ㄹ 거예요)",
    "formal": "formal present (-ㅂ니다/-습니다)",
    "honorific": "honorific present (-(으)세요)",
    "honorific_past": "honorific past (-(으)셨어요)",
    "neg_an": "negative with 안",
    "neg_ji": "negative with -지 않아요",
    "go": "joined with -고 (and)",
    "go_sipda": "want to (-고 싶어요)",
    "go_itda": "doing it now (-고 있어요)",
    "modifier": "describing a noun (-(으)ㄴ)",
    "become": "becoming (-아/어져요)",
}
ADJECTIVE_ONLY = {"modifier", "become"}
VERB_ONLY = {"go_sipda", "go_itda"}

ANIDA = {"present": ["아니에요"], "past": ["아니었어요"], "future": ["아닐 거예요"], "formal": ["아닙니다"],
         "honorific": ["아니세요"], "honorific_past": ["아니셨어요"], "go": ["아니고"], "modifier": ["아닌"]}

HONORIFIC_VERBS = {"먹다": ["드시", "잡수시"], "마시다": ["드시"], "자다": ["주무시"], "있다": ["계시"], "말하다": ["말씀하시"]}

RULES = {
    "regular": "",
    "하다": "하다 verbs: 하 + 여 contracts to 해.",
    "아니다": "아니다: polite 아니에요, past 아니었어요.",
    "ㄷ": "ㄷ-irregular: before a vowel (-아/어, -으) the final ㄷ becomes ㄹ (듣다 → 들어요, 들으세요).",
    "ㅂ": "ㅂ-irregular: before a vowel the final ㅂ becomes 우 (덥다 → 더워요, 더운). 돕다 and 곱다 take 와 (도와요).",
    "ㅅ": "ㅅ-irregular: before a vowel the final ㅅ drops and nothing contracts (짓다 → 지어요, 지으세요).",
    "ㅎ": "ㅎ-irregular: before -아/어 the ㅎ drops and the vowel becomes ㅐ (빨갛다 → 빨개요); before -으 the ㅎ and 으 drop (빨간).",
    "르": "르-irregular: before -아/어, 르 becomes ㄹ라/ㄹ러 (모르다 → 몰라요, 부르다 → 불러요).",
    "으": "으-irregular: before -아/어 the ㅡ drops (쓰다 → 써요, 바쁘다 → 바빠요).",
    "ㄹ": "ㄹ-stem: the ㄹ drops before ㄴ, ㅂ, ㅅ, and no 으 is added (알다 → 아세요, 압니다, 알 거예요).",
}


class ConjugationError(Exception):
    """The engine cannot conjugate this verb with this ending."""


def split(syllable):
    code = ord(syllable) - BASE
    if not 0 <= code < 11172:
        raise ConjugationError(f"Not a Hangul syllable: {syllable}")
    return code // (VOWELS * FINALS), (code % (VOWELS * FINALS)) // FINALS, code % FINALS


def join(lead, vowel, final=0):
    return chr(BASE + (lead * VOWELS + vowel) * FINALS + final)


def with_final(text, final):
    lead, vowel, old = split(text[-1])
    if old:
        raise ConjugationError(f"{text} already has a final consonant")
    return text[:-1] + join(lead, vowel, final)


def eo_syllable(vowel):
    return "아" if vowel in BRIGHT else "어"


def infinitive(stem, cls):
    """The -아/어 forms (first is the usual one): 가, 먹어, 해, 봐/보아, 도와, 빨개, 몰라."""
    lead, vowel, final = split(stem[-1])
    head = stem[:-1]
    if cls == "하다":
        return [head + "해"]
    if cls == "아니다":
        return [stem + "어"]
    if cls == "ㄷ":
        return [head + join(lead, vowel, T["ㄹ"]) + eo_syllable(vowel)]
    if cls == "ㅂ":
        base = head + join(lead, vowel)
        return [base + ("와" if stem in ("돕", "곱") else "워")]
    if cls == "ㅅ":
        return [head + join(lead, vowel) + eo_syllable(vowel)]
    if cls == "ㅎ":
        changed = {V["ㅏ"]: V["ㅐ"], V["ㅓ"]: V["ㅐ"], V["ㅑ"]: V["ㅒ"], V["ㅕ"]: V["ㅖ"]}.get(vowel)
        if changed is None:
            raise ConjugationError(f"Unexpected ㅎ-irregular vowel in {stem}")
        return [head + join(lead, changed)]
    if cls == "르":
        if len(stem) < 2 or stem[-1] != "르":
            raise ConjugationError(f"{stem} is not a 르 stem")
        p_lead, p_vowel, _ = split(stem[-2])
        return [stem[:-2] + join(p_lead, p_vowel, T["ㄹ"]) + ("라" if p_vowel in BRIGHT else "러")]
    if cls == "으":
        if vowel != V["ㅡ"] or final:
            raise ConjugationError(f"{stem} is not a 으 stem")
        if len(stem) == 1:
            return [join(lead, V["ㅓ"])]
        bright = split(stem[-2])[1] in BRIGHT
        return [head + join(lead, V["ㅏ"] if bright else V["ㅓ"])]
    if final:
        return [stem + eo_syllable(vowel)]
    if vowel in (V["ㅏ"], V["ㅓ"], V["ㅕ"]):
        return [stem]
    if vowel in (V["ㅐ"], V["ㅔ"]):
        return [stem, stem + "어"]
    if vowel == V["ㅗ"]:
        contracted = head + join(lead, V["ㅘ"])
        return [contracted] if lead == L_IEUNG else [contracted, stem + "아"]
    if vowel == V["ㅜ"]:
        return [head + join(lead, V["ㅝ"]), stem + "어"]
    if vowel == V["ㅣ"]:
        return [head + join(lead, V["ㅕ"]), stem + "어"]
    if vowel == V["ㅚ"]:
        return [head + join(lead, V["ㅙ"]), stem + "어"]
    return [stem + eo_syllable(vowel)]


def open_stem(stem, cls):
    """The stem as it stands before endings that start with 으 or attach to an open syllable
    (-세요, -ㄹ, -ㄴ, -ㅂ니다): 먹으, 가, 들으, 더우, 지으, 빨가, 아."""
    lead, vowel, final = split(stem[-1])
    head = stem[:-1]
    if cls == "ㄷ":
        return head + join(lead, vowel, T["ㄹ"]) + "으"
    if cls == "ㅂ":
        return head + join(lead, vowel) + "우"
    if cls == "ㅅ":
        return head + join(lead, vowel) + "으"
    if cls in ("ㅎ", "ㄹ"):
        return head + join(lead, vowel)
    return stem + "으" if final else stem


def formal(stem, cls):
    final = split(stem[-1])[2]
    if cls == "ㄹ":
        return with_final(open_stem(stem, cls), T["ㅂ"]) + "니다"
    if final:
        return stem + "습니다"
    return with_final(stem, T["ㅂ"]) + "니다"


def conjugate(dictionary_form, cls, ending, adjective=False):
    """Every accepted form of the word with the ending, the usual one first."""
    if ending not in ENDINGS:
        raise ConjugationError(f"Unknown ending: {ending}")
    if cls not in CLASSES:
        raise ConjugationError(f"Unknown class: {cls}")
    if not dictionary_form.endswith("다") or len(dictionary_form) < 2:
        raise ConjugationError(f"Not a dictionary form: {dictionary_form}")
    if ending in ADJECTIVE_ONLY and not adjective:
        raise ConjugationError(f"{ENDINGS[ending]} is for adjectives")
    if ending in VERB_ONLY and adjective:
        raise ConjugationError(f"{ENDINGS[ending]} is for verbs")
    stem = dictionary_form[:-1]
    if cls == "아니다":
        if ending not in ANIDA:
            raise ConjugationError(f"아니다 has no {ENDINGS[ending]} form")
        return ANIDA[ending]
    forms = infinitive(stem, cls)
    if ending == "present":
        return [f + "요" for f in forms]
    if ending == "past":
        return [with_final(f, T["ㅆ"]) + "어요" for f in forms]
    if ending == "become":
        return [f + "져요" for f in forms]
    opened = open_stem(stem, cls)
    if ending == "future":
        return [with_final(opened, T["ㄹ"]) + " 거예요"]
    if ending == "formal":
        return [formal(stem, cls)]
    if ending in ("honorific", "honorific_past"):
        tail = "세요" if ending == "honorific" else "셨어요"
        result = [opened + tail]
        for special in HONORIFIC_VERBS.get(dictionary_form, []):
            result.append(special[:-1] + tail)
        return result
    if ending == "modifier":
        if stem.endswith(("있", "없")):
            return [stem + "는"]
        return [with_final(opened, T["ㄴ"])]
    if ending == "neg_an":
        noun = stem[:-1]
        # 공부하다 is noun + 하다, so 안 goes before 하다. 좋아하다 (좋아 + 하다) and 하다-adjectives take 안 in front.
        if cls == "하다" and noun and not adjective and not noun.endswith(("아", "어")):
            return [f"{noun} 안 해요"]
        return [f"안 {f}요" for f in forms]
    suffix = {"neg_ji": "지 않아요", "go": "고", "go_sipda": "고 싶어요", "go_itda": "고 있어요"}[ending]
    return [stem + suffix]


def candidate_classes(dictionary_form):
    """The classes a word could belong to, judging by its spelling alone."""
    stem = dictionary_form[:-1]
    if dictionary_form == "아니다":
        return ["아니다"]
    if stem.endswith("하"):
        return ["하다"]
    lead, vowel, final = split(stem[-1])
    if stem[-1] == "르" and len(stem) > 1:
        return ["르", "으"]
    if vowel == V["ㅡ"] and not final:
        return ["으"]
    return {T["ㄷ"]: ["regular", "ㄷ"], T["ㅂ"]: ["regular", "ㅂ"], T["ㅅ"]: ["regular", "ㅅ"],
            T["ㅎ"]: ["regular", "ㅎ"], T["ㄹ"]: ["ㄹ"]}.get(final, ["regular"])


def detect_class(dictionary_form, listed_forms):
    """The class whose forms match the conjugations a dictionary lists (도와, 도우니), or None."""
    listed = set(listed_forms)
    stem = dictionary_form[:-1]
    matches = []
    for cls in candidate_classes(dictionary_form):
        try:
            eo_ok = infinitive(stem, cls)[0] in listed
            uni_ok = (open_stem(stem, cls) + "니") in listed if any(f.endswith("니") for f in listed) else True
        except ConjugationError:
            continue
        if eo_ok and uni_ok:
            matches.append(cls)
    return matches[0] if len(matches) == 1 else None


def rule_for(cls, ending):
    text = {"present": "Polite present: stem + -아요/-어요 (아 after ㅏ/ㅗ).",
            "past": "Past: stem + -았어요/-었어요 (았 after ㅏ/ㅗ).",
            "future": "Future: stem + -ㄹ 거예요 after a vowel, -을 거예요 after a consonant.",
            "formal": "Formal: stem + -ㅂ니다 after a vowel, -습니다 after a consonant.",
            "honorific": "Honorific: stem + -세요 after a vowel, -으세요 after a consonant.",
            "honorific_past": "Honorific past: stem + -셨어요 after a vowel, -으셨어요 after a consonant.",
            "neg_an": "안 goes right before the verb (for noun + 하다, before 하다: 공부 안 해요).",
            "neg_ji": "Negative: stem + -지 않아요.",
            "go": "Joining: stem + -고, with no change to the stem.",
            "go_sipda": "Want to: stem + -고 싶어요.",
            "go_itda": "Doing now: stem + -고 있어요.",
            "modifier": "Before a noun: stem + -ㄴ after a vowel, -은 after a consonant (있다/없다 take -는).",
            "become": "Becoming: the -아/어 form + -져요."}[ending]
    return (text + " " + RULES[cls]).strip()
