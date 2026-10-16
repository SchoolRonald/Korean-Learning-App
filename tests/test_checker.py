import unicodedata

import pytest

from app.checker import answer_variants, check, check_entry, jamo


def wrong(result):
    return [s for s in result["syllables"] if not s["ok"]]


def test_exact_match():
    r = check("선생님", "선생님")
    assert r["correct"] and not wrong(r) and r["feedback"] == []


def test_whitespace_ignored_at_ends():
    assert check("학교", "  학교 ")["correct"]


def test_nfd_input_matches_nfc():
    assert check("한국", unicodedata.normalize("NFD", "한국"))["correct"]


def test_jamo_split():
    assert jamo("한") == ("ᄒ", "ᅡ", "ᆫ")
    assert jamo("가") == ("ᄀ", "ᅡ", "")
    assert jamo("a") is None


def test_wrong_vowel():
    r = check("선생님", "선샹님")
    assert not r["correct"]
    [s] = wrong(r)
    assert (s["expected"], s["typed"], s["parts"]) == ("생", "샹", ["vowel"])
    assert r["feedback"] == ["Syllable 2: expected 생, you typed 샹 (vowel wrong)"]


def test_wrong_first_consonant():
    [s] = wrong(check("고양이", "코양이"))
    assert s["parts"] == ["first consonant"]


def test_missing_final_consonant():
    [s] = wrong(check("책", "채"))
    assert s["parts"] == ["final consonant"]


def test_wrong_final_consonant():
    [s] = wrong(check("밥", "밮"))
    assert s["parts"] == ["final consonant"]


def test_several_parts_wrong():
    [s] = wrong(check("물", "멀"))
    assert s["parts"] == ["vowel"]
    [s] = wrong(check("물", "볼"))
    assert s["parts"] == ["first consonant", "vowel"]


def test_missing_syllable_does_not_shift_rest():
    r = check("고양이", "고이")
    [s] = wrong(r)
    assert (s["expected"], s["typed"]) == ("양", "")
    assert r["feedback"] == ["Syllable 2: missing 양"]


def test_extra_syllable():
    r = check("물", "물물")
    assert not r["correct"]
    [s] = wrong(r)
    assert (s["expected"], s["typed"]) == ("", "물")


def test_empty_answer():
    r = check("사과", "")
    assert not r["correct"]
    assert len(wrong(r)) == 2


def test_latin_letters_hint():
    r = check("물", "mul")
    assert not r["correct"] and "Korean keyboard" in r["hint"]
    assert "hint" not in check("물", "물")


@pytest.mark.parametrize("entry, expected", [
    ("물", ["물"]),
    ("아기 / 애기", ["아기", "애기"]),
    ("평생 (동안)", ["평생", "평생 동안"]),
    ("냄새 (나다)", ["냄새", "냄새 나다"]),
    ("1월 (일월)", ["1월", "일월"]),
    ("옛 _____", ["옛"]),
    ("어때?", ["어때"]),
])
def test_answer_variants(entry, expected):
    assert answer_variants(entry) == expected


@pytest.mark.parametrize("entry, answer", [
    ("아기 / 애기", "애기"),
    ("1월 (일월)", "일월"),
    ("1월 (일월)", "1월"),
    ("냄새 (나다)", "냄새나다"),
    ("어때?", "어때?"),
    ("옛 _____", "옛"),
])
def test_check_entry_accepts_listed_forms(entry, answer):
    assert check_entry(entry, answer)["correct"]


def test_spacing_ignored_with_note():
    r = check_entry("관심이 있다", "관심이있다")
    assert r["correct"] and r["note"] == "Correct. Usually written 관심이 있다."


def test_check_entry_feedback_uses_closest_form():
    r = check_entry("아기 / 애기", "애가")
    assert not r["correct"] and r["expected"] == "애기"
    assert r["feedback"] == ["Syllable 2: expected 기, you typed 가 (vowel wrong)"]


def test_check_entry_still_rejects_wrong():
    assert not check_entry("평생 (동안)", "동안")["correct"]
