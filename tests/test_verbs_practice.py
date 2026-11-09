import json

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import practice, verbs
from tests.test_practice import FakeAI, answer


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


def add_word(hangul, english, lesson=1, learned=True):
    conn = main.db()
    cur = conn.execute("INSERT INTO words (hangul, english, lesson) VALUES (?, ?, ?)", (hangul, english, lesson))
    if learned:
        conn.execute("INSERT INTO learned (word_id, learned_at) VALUES (?, 'now')", (cur.lastrowid,))
    conn.commit()


def conj_item(client, point="past-tense"):
    r = client.get(f"/api/grammar/item?point={point}&type=conjugate&lesson=25")
    assert r.status_code == 200, r.text
    return r.json()


def test_conjugation_items_come_from_the_engine(client, ai):
    item = conj_item(client)
    assert item["type"] == "conjugate" and item["ending"] == "past" and item["verb"].endswith("다")
    assert ai.calls == []
    row = main.db().execute("SELECT answers, checked FROM grammar_items WHERE id = ?", (item["id"],)).fetchone()
    assert json.loads(row[1])["source"] == "engine"
    right = json.loads(row[0])[0]
    assert answer(client, item["id"], right)["verdict"] == "correct"


def test_wrong_conjugation_shows_the_rule_without_ai(client, ai):
    item = conj_item(client, "irregular-b")
    result = answer(client, item["id"], "돕었어요")
    assert result["verdict"] == "incorrect" and result["graded_by"] == "exact"
    assert "ㅂ-irregular" in result["reason"]
    assert ai.calls == []


def test_irregular_points_only_drill_their_class(client, ai):
    for _ in range(5):
        item = conj_item(client, "irregular-reu")
        assert item["verb"] in {"모르다", "부르다", "다르다", "빠르다"}


def test_adjective_endings_only_use_adjectives(client, ai):
    for _ in range(5):
        item = conj_item(client, "attributive-adjective-n-eun")
        assert dict((h, a) for h, _, _, a in verbs.SEED)[item["verb"]] is True


def test_learned_verbs_with_known_classes_come_first(client, ai):
    add_word("씻다", "to wash")
    main.db().execute("INSERT INTO verb_classes (hangul, english, adjective, class, source, created_at) "
                      "VALUES ('씻다', 'to wash', 0, 'regular', 'krdict', 'now')")
    main.db().commit()
    seen = {conj_item(client)["verb"] for _ in range(8)}
    assert "씻다" in seen


def test_practice_plan_starts_with_conjugation_for_conjugation_points(client):
    point = client.get("/api/grammar/point?id=past-tense&lesson=25").json()["point"]
    assert point["practice_plan"] == ["conjugate", "fill", "transform", "translate"]
    other = client.get("/api/grammar/point?id=particle-eseo&lesson=25").json()["point"]
    assert other["practice_plan"] == ["fill", "compare", "spot", "translate"]


def test_conjugate_falls_back_for_points_without_engine_support(client, ai):
    r = client.get("/api/grammar/item?point=particle-eseo&type=conjugate&lesson=25").json()
    assert r["type"] != "conjugate"


def entry(english, forms, pos="동사"):
    return {"word": "묻다", "pos": pos, "forms": forms, "english": english}


def test_choose_class_uses_the_meaning_for_homographs():
    entries = [entry(["ask; inquire"], ["물어", "물으니"]), entry(["bury"], ["묻어", "묻으니"])]
    assert verbs.choose_class(entries, "to ask")[0] == "ㄷ"
    assert verbs.choose_class(entries, "to bury")[0] == "regular"
    assert verbs.choose_class(entries, "to question")[0] is None


def test_classify_saves_the_class(client):
    def get(endpoint, params):
        if endpoint == "search":
            return ("<channel><item><target_code>1</target_code><word>돕다</word><sup_no>0</sup_no>"
                    "<pos>동사</pos></item></channel>")
        return ("<channel><item><target_code>1</target_code><word_info><word>돕다</word><pos>동사</pos>"
                "<conjugation_info><conjugation>도와</conjugation></conjugation_info>"
                "<conjugation_info><conjugation>도우니</conjugation></conjugation_info>"
                "<sense_info><translation><trans_word><![CDATA[help]]></trans_word></translation></sense_info>"
                "</word_info></item></channel>")
    assert verbs.classify(main.db(), "돕다", "to help", get) == "ㅂ"
    row = main.db().execute("SELECT class, adjective FROM verb_classes WHERE hangul = '돕다'").fetchone()
    assert tuple(row) == ("ㅂ", 0)


def test_two_forms_in_one_field_are_both_read():
    from app import krdict
    xml = ("<channel><item><word_info><pos>동사</pos><conjugation_info><conjugation>말하여(말해)</conjugation>"
           "</conjugation_info><conjugation_info><conjugation>말하니</conjugation></conjugation_info></word_info></item></channel>")
    assert krdict.parse_conjugations(xml)["forms"] == ["말하여", "말해", "말하니"]
    assert verbs.choose_class([{"word": "말하다", "pos": "동사", "forms": ["말하여", "말해", "말하니"],
                                "english": ["speak"]}], "to speak")[0] == "하다"


def test_unreachable_krdict_pauses_lookups(client, monkeypatch):
    from app import krdict
    monkeypatch.setenv("KRDICT_API_KEY", "k")
    monkeypatch.setattr(verbs, "_paused_until", 0.0)
    calls = []

    def down(endpoint, params):
        calls.append(endpoint)
        raise krdict.KrdictError("timed out")
    add_word("씻다", "to wash")
    add_word("닦다", "to wipe")
    first = verbs.drill_verbs(main.db(), 25, get=down)
    assert calls == ["search"] and first
    verbs.drill_verbs(main.db(), 25, get=down)
    assert calls == ["search"]
    assert main.db().execute("SELECT count(*) FROM verb_classes").fetchone()[0] == 0


def test_word_list_verbs_keep_only_dictionary_forms(client):
    add_word("가다", "to go")
    add_word("학생", "student")
    add_word("평생 (동안)", "to be lifelong")
    assert [v[0] for v in verbs.word_list_verbs(main.db(), 25)] == ["가다"]


def test_transform_items_are_cleaned():
    good = {"sentence": "저는 학교에 가요.", "instruction": "Change it to the past tense", "english": "I went to school.",
            "answers": ["저는 학교에 갔어요."], "reason": "r"}
    assert practice.clean_item("transform", good)["prompt"]["instruction"] == "Change it to the past tense"
    assert practice.clean_item("transform", {**good, "answers": ["저는 학교에 가요"]}) is None
    assert practice.clean_item("transform", {**good, "instruction": ""}) is None


def test_prefetch_writes_only_when_no_items_are_left(client, ai):
    practice.prefetch_items(main.db(), "particle-eseo", 25)
    assert [c[0] for c in ai.calls] == ["grammar-items", "grammar-check"]
    for row in main.db().execute("SELECT id FROM grammar_items WHERE type = 'translate'").fetchall():
        main.db().execute("INSERT INTO grammar_attempts (point_id, item_id, source, answer, verdict, correct, ts) "
                          "VALUES ('particle-eseo', ?, 'practice', 'x', 'correct', 1, 'now')", (row[0],))
    main.db().commit()
    practice.prefetch_items(main.db(), "particle-eseo", 25)
    assert len(ai.calls) == 2
