import json
import re

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import grammar, practice
from app.llm import TEACHING_MODEL, LLMError

POINT = next(p for p in grammar.points() if p["related"])
LONELY = next(p for p in grammar.points() if not p["related"])


def items_data():
    return {
        "fill": [{"sentence": f"저___ 학생{i}이에요.", "english": "I am a student.", "answers": ["는"], "reason": "저 ends in a vowel."}
                 for i in range(3)],
        "compare": [{"sentence": "저___ 학생이에요.", "english": "I am a student.", "choices": ["는", "가"],
                     "answers": ["는", "가"], "reason": "Both work, with different focus."}],
        "spot": [{"wrong": "저은 학생이에요.", "english": "I am a student.", "answers": ["저는 학생이에요."], "reason": "Vowel, so 는."}],
        "translate": [{"english": "I am a student.", "answers": ["저는 학생이에요."], "reason": "Use 는."}],
    }


def keep_all(prompt):
    """A check that keeps every item with its own answers."""
    verdicts = []
    for block in prompt.split("\n\n"):
        found = re.search(r"\[id (\d+)\]", block)
        if found:
            answers = re.search(r"accepted answers: (.*)", block).group(1).split(" / ")
            verdicts.append({"id": int(found.group(1)), "verdict": "keep", "answers": answers, "reason": "", "problem": ""})
    return verdicts


class FakeAI:
    def __init__(self, grade=("almost", "Use 는 here."), check=None):
        self.calls = []
        self.grade = grade
        self.check = check or (lambda verdicts: verdicts)

    def __call__(self, purpose, system, prompt, schema, **kwargs):
        self.calls.append((purpose, kwargs.get("model")))
        if purpose == "grammar-items":
            return items_data()
        if purpose == "grammar-check":
            return {"items": self.check(keep_all(prompt))}
        if purpose == "grammar-grade":
            if isinstance(self.grade, Exception):
                raise self.grade
            return {"verdict": self.grade[0], "reason": self.grade[1]}
        return {}


@pytest.fixture
def ai(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(practice, "call_json", fake)
    return fake


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "db_path", tmp_path / "test.db")
    with TestClient(main.app) as c:
        yield c


def item(client, point=POINT, item_type="fill"):
    r = client.get(f"/api/grammar/item?point={point['id']}&type={item_type}&lesson=25")
    assert r.status_code == 200, r.text
    return r.json()


def answer(client, item_id, text, source="practice"):
    return client.post("/api/grammar/answer", json={"item_id": item_id, "answer": text, "source": source}).json()


def test_clean_item_rejects_broken_items():
    assert practice.clean_item("fill", {"sentence": "no blank", "english": "x", "answers": ["는"], "reason": "r"}) is None
    assert practice.clean_item("compare", {"sentence": "a ___", "english": "x", "choices": ["는", "가"],
                                           "answers": ["을"], "reason": "r"}) is None
    assert practice.clean_item("spot", {"wrong": "저는 학생이에요.", "english": "x", "answers": ["저는 학생이에요"],
                                        "reason": "r"}) is None
    good = practice.clean_item("fill", {"sentence": "저___ 학생이에요.", "english": "x", "answers": ["는"], "reason": "r"})
    assert good == {"prompt": {"sentence": "저___ 학생이에요.", "english": "x"}, "answers": ["는"], "reason": "r"}


@pytest.mark.parametrize("item_type,raw", [
    ("fill", {"sentence": "저는 학생___.", "english": "I am a student.", "answers": ["이다"], "reason": "r"}),
    ("compare", {"sentence": "저것은 나무___.", "english": "That is a tree.", "choices": ["이다", "가"],
                 "answers": ["이다"], "reason": "r"}),
    ("compare", {"sentence": "책은 탁자 위에 ___.", "english": "x", "choices": ["있다", "이다"],
                 "answers": ["있다"], "reason": "r"}),
    ("compare", {"sentence": "저는 의자를 ___.", "english": "x", "choices": ["사요", "사다"], "answers": ["사요"], "reason": "r"}),
    ("fill", {"sentence": "이것은 ___?", "english": "x", "answers": ["뭐에요"], "reason": "r"}),
    ("fill", {"sentence": "저는 학생 ___.", "english": "x", "answers": ["이에요"], "reason": "r"}),
    ("translate", {"english": "I will eat.", "answers": ["먹을 것이에요"], "reason": "r"}),
])
def test_dictionary_forms_and_misspellings_are_rejected(item_type, raw):
    assert practice.clean_item(item_type, raw) is None


@pytest.mark.parametrize("item_type,raw", [
    ("fill", {"sentence": "저는 학생___.", "english": "x", "answers": ["이에요"], "reason": "r"}),
    ("fill", {"sentence": "저는 학생___.", "english": "x", "answers": ["입니다"], "reason": "r"}),
    ("compare", {"sentence": "저___ 학생이에요.", "english": "x", "choices": ["는", "을"], "answers": ["는"], "reason": "r"}),
    ("fill", {"sentence": "저는 ___ 사람이에요.", "english": "x", "answers": ["좋은"], "reason": "r"}),
    ("fill", {"sentence": "저는 의사가 ___.", "english": "x", "answers": ["아니에요"], "reason": "r"}),
])
def test_correct_items_are_kept(item_type, raw):
    assert practice.clean_item(item_type, raw) is not None


def test_misspelled_answers_are_dropped_from_a_good_item():
    item = practice.clean_item("fill", {"sentence": "이것은 ___?", "english": "x", "answers": ["뭐예요", "뭐에요"], "reason": "r"})
    assert item["answers"] == ["뭐예요"]


@pytest.mark.parametrize("text,problem", [
    ("뭐에요?", "뭐에요"), ("저에요", "저에요"), ("학생 이에요", "space"), ("학생이예요", "이예요"), ("먹을 것이에요", "것이에요"),
])
def test_korean_problems_found(text, problem):
    assert any(problem in p for p in practice.korean_problems(text))


@pytest.mark.parametrize("text", ["뭐예요?", "아니에요", "학생이에요", "의자예요", "거예요", "책이에요", "어디예요?"])
def test_korean_problems_clean(text):
    assert practice.korean_problems(text) == []


def test_check_runs_again_for_items_without_a_verdict(client, monkeypatch):
    calls = []

    def check(verdicts):
        calls.append(len(verdicts))
        return verdicts[1:] if len(calls) == 1 else verdicts
    monkeypatch.setattr(practice, "call_json", FakeAI(check=check))
    item(client)
    assert calls[1] == 1 and saved()[0]["checked"]["verdict"] == "keep"


def test_saved_bad_items_are_never_served(client, ai):
    conn = main.db()
    conn.execute(
        "INSERT INTO grammar_items (point_id, type, prompt, answers, reason, created_at) VALUES (?, 'fill', ?, ?, 'r', 'now')",
        (POINT["id"], '{"sentence": "저는 학생___.", "english": "I am a student."}', '["이다"]'),
    )
    conn.commit()
    served = item(client)
    assert served["sentence"] != "저는 학생___."
    assert ("grammar-items", TEACHING_MODEL) in ai.calls


def test_items_are_written_by_sonnet_once_per_batch(client, ai):
    first = item(client)
    assert first["type"] == "fill" and "___" in first["sentence"] and "answers" not in first
    assert ai.calls == [("grammar-items", TEACHING_MODEL), ("grammar-check", TEACHING_MODEL)]
    item(client, item_type="translate")
    assert len(ai.calls) == 2


def test_new_batch_only_after_every_item_of_a_type_is_seen(client, ai):
    for _ in range(3):
        answer(client, item(client)["id"], "는")
    assert len(ai.calls) == 2
    item(client)
    assert [c[0] for c in ai.calls] == ["grammar-items", "grammar-check"] * 2


def test_fill_accepts_the_blank_or_the_whole_sentence(client, ai):
    first = item(client)
    assert answer(client, first["id"], "는")["verdict"] == "correct"
    second = item(client)
    assert answer(client, second["id"], second["sentence"].replace("___", "는"))["correct"] is True
    third = item(client)
    assert [c[0] for c in ai.calls] == ["grammar-items", "grammar-check"]
    result = answer(client, third["id"], "가")
    assert result["verdict"] == "almost" and result["graded_by"] == "llm" and result["answers"] == ["는"]
    assert [c[0] for c in ai.calls][-1] == "grammar-grade"


def test_compare_can_accept_both_choices(client, ai):
    first = item(client, item_type="compare")
    assert first["choices"] == ["는", "가"]
    assert answer(client, first["id"], "가")["correct"] is True


def test_compare_falls_back_when_point_has_no_related(client, ai):
    assert item(client, LONELY, "compare")["type"] != "compare"


def test_translate_exact_match_needs_no_grading_call(client, ai):
    first = item(client, item_type="translate")
    assert answer(client, first["id"], "저는  학생이에요")["graded_by"] == "exact"
    assert "grammar-grade" not in [c[0] for c in ai.calls]


def test_free_answers_are_graded_by_haiku_and_almost_is_a_miss(client, ai):
    first = item(client, item_type="spot")
    result = answer(client, first["id"], "제가 학생이에요.")
    assert result["verdict"] == "almost" and result["graded_by"] == "llm" and result["correct"] is False
    assert ("grammar-grade", None) in ai.calls


def test_failed_grading_is_not_recorded(client, monkeypatch):
    monkeypatch.setattr(practice, "call_json", FakeAI(grade=LLMError("down")))
    first = item(client, item_type="translate")
    assert answer(client, first["id"], "뭐예요")["verdict"] == "ungraded"
    assert main.db().execute("SELECT count(*) FROM grammar_attempts").fetchone()[0] == 0


def test_confidence_rises_on_right_and_never_on_wrong(client, ai):
    right = answer(client, item(client)["id"], "는")
    assert right["confidence"] > right["confidence_before"] == 0
    wrong = answer(client, item(client)["id"], "가")
    assert wrong["confidence"] < wrong["confidence_before"]


def test_explain_writes_practice_items_ahead(client, ai, monkeypatch):
    monkeypatch.setattr(grammar, "call_json", lambda *a, **k: {
        "intro": "i", "rule": "r", "table": [], "nuance": "n", "mistakes": [],
        "examples": [{"korean": "저는 학생이에요.", "english": "e", "highlight": "는", "note": "", "parts": [], "tokens": []}] * 8,
    })
    client.get(f"/api/grammar/explain?point={POINT['id']}&lesson=25")
    assert ("grammar-items", TEACHING_MODEL) in ai.calls


def test_review_needs_learned_points(client, ai):
    assert client.get("/api/grammar/review?lesson=25").status_code == 404


def test_review_picks_weak_learned_points(client, ai):
    for p in grammar.points()[:4]:
        client.post("/api/grammar/done", json={"point": p["id"]})
    r = client.get("/api/grammar/review?lesson=25").json()
    assert r["point"]["id"] in {p["id"] for p in grammar.points()[:4]}


def test_mixed_review_skips_strong_points(client, ai):
    client.post("/api/grammar/done", json={"point": POINT["id"]})
    for _ in range(3):
        answer(client, item(client)["id"], "는")
    strong = practice.point_confidence(main.db(), POINT["id"])
    assert strong > 0.5
    assert client.get("/api/grammar/review?lesson=25&below=0.5").status_code == 404


def test_debug_lists_learned_points_with_pool(client, ai):
    client.post("/api/grammar/done", json={"point": POINT["id"]})
    d = client.get("/api/grammar/debug?lesson=25").json()
    assert [p["id"] for p in d["points"]] == [POINT["id"]] and d["review_pool"] == [POINT["id"]]


def test_unknown_item_is_404(client):
    assert client.post("/api/grammar/answer", json={"item_id": 999, "answer": "는"}).status_code == 404


def saved(point_id=POINT["id"]):
    rows = main.db().execute("SELECT type, answers, reason, checked FROM grammar_items WHERE point_id = ? ORDER BY id",
                             (point_id,)).fetchall()
    return [{"type": r[0], "answers": json.loads(r[1]), "reason": r[2], "checked": json.loads(r[3])} for r in rows]


def test_check_drops_and_fixes_items(client, monkeypatch):
    def check(verdicts):
        verdicts[0].update(verdict="drop", problem="Unnatural sentence.")
        verdicts[1].update(verdict="fix", answers=["는", "이"], reason="Fixed reason.", problem="Missing answer.")
        return verdicts
    monkeypatch.setattr(practice, "call_json", FakeAI(check=check))
    first = item(client)
    items = saved()
    assert items[0]["checked"] == {"verdict": "drop", "problem": "Unnatural sentence."}
    assert items[1]["answers"] == ["는", "이"] and items[1]["reason"] == "Fixed reason."
    assert first["sentence"] == "저___ 학생1이에요."


def test_fix_that_breaks_item_rules_is_dropped(client, monkeypatch):
    def check(verdicts):
        for v in verdicts:
            v.update(verdict="fix", answers=["을"])
        return verdicts
    monkeypatch.setattr(practice, "call_json", FakeAI(check=check))
    client.get(f"/api/grammar/item?point={POINT['id']}&type=fill&lesson=25")
    compare = next(i for i in saved() if i["type"] == "compare")
    assert compare["checked"]["verdict"] == "drop" and "item rules" in compare["checked"]["problem"]


def test_missing_verdict_drops_the_item(client, monkeypatch):
    monkeypatch.setattr(practice, "call_json", FakeAI(check=lambda verdicts: verdicts[1:]))
    item(client)
    assert saved()[0]["checked"]["verdict"] == "drop"


def test_old_unchecked_items_are_checked_before_serving(client, ai):
    conn = main.db()
    for i in range(3):
        for item_type, prompt, answers in [
            ("fill", {"sentence": f"저___ 의사{i}예요.", "english": "x"}, ["는"]),
            ("compare", {"sentence": "저___ 의사예요.", "english": "x", "choices": ["는", "가"]}, ["는"]),
            ("spot", {"wrong": "저은 의사예요.", "english": "x"}, ["저는 의사예요."]),
            ("translate", {"english": "I am a doctor."}, ["저는 의사예요."]),
        ]:
            conn.execute("INSERT INTO grammar_items (point_id, type, prompt, answers, reason, created_at) "
                         "VALUES (?, ?, ?, ?, 'r', 'now')",
                         (POINT["id"], item_type, json.dumps(prompt, ensure_ascii=False),
                          json.dumps(answers, ensure_ascii=False)))
    conn.commit()
    served = item(client)
    assert served["sentence"] == "저___ 의사0예요."
    assert [c[0] for c in ai.calls] == ["grammar-check"]
    assert all(i["checked"] for i in saved())
