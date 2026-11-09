import pytest

from app.conjugate import ENDINGS, ConjugationError, conjugate, detect_class

# (word, class, adjective, ending, expected first form, other accepted forms)
CASES = [
    ("가다", "regular", False, "present", "가요", []),
    ("가다", "regular", False, "past", "갔어요", []),
    ("가다", "regular", False, "future", "갈 거예요", []),
    ("가다", "regular", False, "formal", "갑니다", []),
    ("가다", "regular", False, "honorific", "가세요", []),
    ("가다", "regular", False, "honorific_past", "가셨어요", []),
    ("가다", "regular", False, "neg_an", "안 가요", []),
    ("가다", "regular", False, "neg_ji", "가지 않아요", []),
    ("가다", "regular", False, "go", "가고", []),
    ("가다", "regular", False, "go_sipda", "가고 싶어요", []),
    ("가다", "regular", False, "go_itda", "가고 있어요", []),
    ("먹다", "regular", False, "present", "먹어요", []),
    ("먹다", "regular", False, "past", "먹었어요", []),
    ("먹다", "regular", False, "future", "먹을 거예요", []),
    ("먹다", "regular", False, "formal", "먹습니다", []),
    ("먹다", "regular", False, "honorific", "먹으세요", ["드세요", "잡수세요"]),
    ("먹다", "regular", False, "honorific_past", "먹으셨어요", ["드셨어요", "잡수셨어요"]),
    ("앉다", "regular", False, "present", "앉아요", []),
    ("보다", "regular", False, "present", "봐요", ["보아요"]),
    ("보다", "regular", False, "past", "봤어요", ["보았어요"]),
    ("오다", "regular", False, "present", "와요", []),
    ("오다", "regular", False, "past", "왔어요", []),
    ("주다", "regular", False, "present", "줘요", ["주어요"]),
    ("마시다", "regular", False, "present", "마셔요", ["마시어요"]),
    ("마시다", "regular", False, "past", "마셨어요", ["마시었어요"]),
    ("되다", "regular", False, "present", "돼요", ["되어요"]),
    ("보내다", "regular", False, "present", "보내요", ["보내어요"]),
    ("서다", "regular", False, "present", "서요", []),
    ("켜다", "regular", False, "present", "켜요", []),
    ("쉬다", "regular", False, "present", "쉬어요", []),
    ("자다", "regular", False, "honorific", "자세요", ["주무세요"]),
    ("하다", "하다", False, "present", "해요", []),
    ("하다", "하다", False, "past", "했어요", []),
    ("하다", "하다", False, "formal", "합니다", []),
    ("하다", "하다", False, "neg_an", "안 해요", []),
    ("공부하다", "하다", False, "neg_an", "공부 안 해요", []),
    ("좋아하다", "하다", False, "neg_an", "안 좋아해요", []),
    ("깨끗하다", "하다", True, "neg_an", "안 깨끗해요", []),
    ("공부하다", "하다", False, "future", "공부할 거예요", []),
    ("아니다", "아니다", True, "present", "아니에요", []),
    ("아니다", "아니다", True, "past", "아니었어요", []),
    ("듣다", "ㄷ", False, "present", "들어요", []),
    ("듣다", "ㄷ", False, "past", "들었어요", []),
    ("듣다", "ㄷ", False, "future", "들을 거예요", []),
    ("듣다", "ㄷ", False, "honorific", "들으세요", []),
    ("듣다", "ㄷ", False, "formal", "듣습니다", []),
    ("듣다", "ㄷ", False, "go", "듣고", []),
    ("걷다", "ㄷ", False, "present", "걸어요", []),
    ("닫다", "regular", False, "present", "닫아요", []),
    ("덥다", "ㅂ", True, "present", "더워요", []),
    ("덥다", "ㅂ", True, "past", "더웠어요", []),
    ("덥다", "ㅂ", True, "modifier", "더운", []),
    ("덥다", "ㅂ", True, "become", "더워져요", []),
    ("돕다", "ㅂ", False, "present", "도와요", []),
    ("돕다", "ㅂ", False, "future", "도울 거예요", []),
    ("돕다", "ㅂ", False, "honorific", "도우세요", []),
    ("돕다", "ㅂ", False, "formal", "돕습니다", []),
    ("쉽다", "ㅂ", True, "modifier", "쉬운", []),
    ("입다", "regular", False, "present", "입어요", []),
    ("짓다", "ㅅ", False, "present", "지어요", []),
    ("짓다", "ㅅ", False, "past", "지었어요", []),
    ("짓다", "ㅅ", False, "honorific", "지으세요", []),
    ("짓다", "ㅅ", False, "go", "짓고", []),
    ("낫다", "ㅅ", False, "present", "나아요", []),
    ("씻다", "regular", False, "present", "씻어요", []),
    ("빨갛다", "ㅎ", True, "present", "빨개요", []),
    ("빨갛다", "ㅎ", True, "past", "빨갰어요", []),
    ("빨갛다", "ㅎ", True, "modifier", "빨간", []),
    ("빨갛다", "ㅎ", True, "formal", "빨갛습니다", []),
    ("빨갛다", "ㅎ", True, "become", "빨개져요", []),
    ("그렇다", "ㅎ", True, "present", "그래요", []),
    ("어떻다", "ㅎ", True, "present", "어때요", []),
    ("하얗다", "ㅎ", True, "present", "하얘요", []),
    ("좋다", "regular", True, "present", "좋아요", []),
    ("좋다", "regular", True, "modifier", "좋은", []),
    ("모르다", "르", False, "present", "몰라요", []),
    ("모르다", "르", False, "past", "몰랐어요", []),
    ("모르다", "르", False, "honorific", "모르세요", []),
    ("부르다", "르", False, "present", "불러요", []),
    ("빠르다", "르", True, "modifier", "빠른", []),
    ("쓰다", "으", False, "present", "써요", []),
    ("쓰다", "으", False, "past", "썼어요", []),
    ("크다", "으", True, "present", "커요", []),
    ("크다", "으", True, "modifier", "큰", []),
    ("크다", "으", True, "become", "커져요", []),
    ("바쁘다", "으", True, "present", "바빠요", []),
    ("예쁘다", "으", True, "present", "예뻐요", []),
    ("아프다", "으", True, "past", "아팠어요", []),
    ("알다", "ㄹ", False, "present", "알아요", []),
    ("알다", "ㄹ", False, "honorific", "아세요", []),
    ("알다", "ㄹ", False, "formal", "압니다", []),
    ("알다", "ㄹ", False, "future", "알 거예요", []),
    ("만들다", "ㄹ", False, "present", "만들어요", []),
    ("만들다", "ㄹ", False, "honorific", "만드세요", []),
    ("만들다", "ㄹ", False, "formal", "만듭니다", []),
    ("길다", "ㄹ", True, "modifier", "긴", []),
    ("길다", "ㄹ", True, "become", "길어져요", []),
    ("작다", "regular", True, "modifier", "작은", []),
    ("맛있다", "regular", True, "modifier", "맛있는", []),
    ("있다", "regular", False, "honorific", "있으세요", ["계세요"]),
]


@pytest.mark.parametrize("word,cls,adjective,ending,first,others", CASES)
def test_conjugation(word, cls, adjective, ending, first, others):
    assert conjugate(word, cls, ending, adjective) == [first, *others]


def test_every_class_and_ending_is_covered():
    assert {c[3] for c in CASES} == set(ENDINGS)
    assert {c[1] for c in CASES} == {"regular", "하다", "아니다", "ㄷ", "ㅂ", "ㅅ", "ㅎ", "르", "으", "ㄹ"}


@pytest.mark.parametrize("word,cls,adjective,ending", [
    ("가다", "regular", False, "modifier"),
    ("크다", "으", True, "go_itda"),
    ("가다", "regular", False, "nope"),
    ("학생", "regular", False, "present"),
])
def test_unsupported_combinations_raise(word, cls, adjective, ending):
    with pytest.raises(ConjugationError):
        conjugate(word, cls, ending, adjective)


@pytest.mark.parametrize("word,listed,cls", [
    ("돕다", ["도와", "도우니", "돕는"], "ㅂ"),
    ("입다", ["입어", "입으니", "입는"], "regular"),
    ("듣다", ["듣는", "들어", "들으니", "듣습니다"], "ㄷ"),
    ("짓다", ["지어", "지으니"], "ㅅ"),
    ("씻다", ["씻어", "씻으니"], "regular"),
    ("빨갛다", ["빨개", "빨가니"], "ㅎ"),
    ("좋다", ["좋아", "좋으니"], "regular"),
    ("모르다", ["몰라", "모르니"], "르"),
    ("따르다", ["따라", "따르니"], "으"),
    ("쓰다", ["써", "쓰니"], "으"),
    ("알다", ["알아", "아니"], "ㄹ"),
    ("공부하다", ["공부해", "공부하니"], "하다"),
    ("가다", ["가", "가니"], "regular"),
])
def test_detect_class_from_dictionary_forms(word, listed, cls):
    assert detect_class(word, listed) == cls


def test_detect_class_gives_up_when_forms_do_not_match():
    assert detect_class("돕다", ["돕어"]) is None
