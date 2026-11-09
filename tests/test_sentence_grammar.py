import json

import httpx
import pytest

from app import grammar, llm, sentences
from app.memory import since_correct, word_stats
from app.sentences import NotReady, get_sentence, grade_sentence
from tests.test_jev import Response
from tests.test_sentences import LESSON_ONE, conn, db_file, fake, few_words_ok, sentence_json, word_id  # noqa: F401


def reply(grammar_ids):
    data = json.loads(sentence_json())
    data["grammar"] = grammar_ids
    return json.dumps(data)


def verdicts(reason="Wrong.", verdict="almost", wrong_words=(), wrong_points=()):
    return json.dumps({"verdict": verdict, "reason": reason, "wrong_words": list(wrong_words),
                       "wrong_points": list(wrong_points)})


def test_sentences_need_lesson_one_grammar(conn, fake):
    conn.execute("DELETE FROM grammar_learned")
    conn.commit()
    with pytest.raises(NotReady, match="Lesson 1 grammar"):
        get_sentence(conn, 1)


def test_prompt_lists_learned_grammar_and_a_focus_point(conn, fake):
    client = fake(sentence_json())
    get_sentence(conn, 1)
    prompt = client.requests[0]["messages"][0]["content"]
    assert all(g in prompt for g in LESSON_ONE) and "Focus grammar point:" in prompt


def test_unlearned_grammar_is_rejected(conn, fake):
    fake(reply(LESSON_ONE + ["past-tense"]))
    with pytest.raises(llm.LLMError, match="not learned"):
        get_sentence(conn, 1)


def test_missing_focus_point_is_rejected(conn, fake, monkeypatch):
    monkeypatch.setattr(sentences, "focus_point", lambda *a, **k: LESSON_ONE[0])
    fake(reply(LESSON_ONE[1:]))
    with pytest.raises(llm.LLMError, match="focus grammar point"):
        get_sentence(conn, 1)


def test_sentences_without_a_grammar_list_are_not_served(conn, fake):
    conn.execute("INSERT INTO sentences (english, korean_ref, word_ids, created_at) VALUES ('Old.', '물이에요.', '[]', 'now')")
    conn.commit()
    fake(sentence_json())
    assert get_sentence(conn, 1)["english"] == "I drink water."


def grammar_answers(conn):
    return [tuple(r) for r in conn.execute("SELECT point_id, source, verdict FROM grammar_attempts ORDER BY id")]


def test_exact_match_marks_every_word_and_point_right(conn, fake):
    fake(sentence_json())
    s = get_sentence(conn, 1)
    r = grade_sentence(conn, s["id"], "저는 물을 마셔요.")
    assert all(w["correct"] for w in r["words"]) and {w["hangul"] for w in r["words"]} == {"물", "마시다"}
    assert [g["id"] for g in r["grammar"]] == LESSON_ONE and all(g["correct"] for g in r["grammar"])
    assert grammar_answers(conn) == [(g, "sentence", "correct") for g in LESSON_ONE]
    stats = {w["hangul"]: w for w in word_stats(conn, 1)}
    assert stats["물"]["attempts"] == 1 and stats["물"]["confidence"] > 0


def test_jev_gives_a_verdict_per_word_and_point(conn, fake, monkeypatch):
    fake(sentence_json())
    s = get_sentence(conn, 1)
    monkeypatch.setenv("JEV_API_KEY", "k")
    low = {"meaning": 0.2, f"word_{word_id(conn, '물')}": 0.1, f"point_{LESSON_ONE[1]}": 0.2}

    def post(url, json, timeout, headers):
        answers = {n: {"type": "noul", "noul": low.get(n, 0.95)} for n in json["questions"]}
        return Response(200, {"answers": answers, "usage": {"input_tokens": 50}})
    monkeypatch.setattr(httpx, "post", post)
    r = grade_sentence(conn, s["id"], "저는 주스를 마셔요.")
    assert r["verdict"] == "incorrect" and r["graded_by"] == "jev"
    assert {w["hangul"]: w["correct"] for w in r["words"]} == {"물": False, "마시다": True}
    assert {g["id"]: g["correct"] for g in r["grammar"]}[LESSON_ONE[1]] is False
    stats = {w["hangul"]: w for w in word_stats(conn, 1)}
    assert stats["물"]["fails"] == 1 and stats["마시다"]["fails"] == 0


def test_haiku_fallback_names_wrong_words_and_points(conn, fake):
    fake(sentence_json(), verdicts(wrong_words=["물"], wrong_points=[LESSON_ONE[2]]))
    s = get_sentence(conn, 1)
    r = grade_sentence(conn, s["id"], "저는 주스 마셔요")
    assert r["graded_by"] == "llm"
    assert {w["hangul"]: w["correct"] for w in r["words"]} == {"물": False, "마시다": True}
    assert ("sentence" in {a[1] for a in grammar_answers(conn)})
    assert dict((a[0], a[2]) for a in grammar_answers(conn))[LESSON_ONE[2]] == "incorrect"


def test_one_sentence_counts_as_one_answer_for_decay(conn, fake):
    from app.drill import record_word_attempt
    water = word_id(conn, "물")
    record_word_attempt(conn, water, "물", True)
    fake(sentence_json())
    s = get_sentence(conn, 1)
    grade_sentence(conn, s["id"], "저는 물을 마셔요.")
    book = word_id(conn, "책")
    record_word_attempt(conn, book, "책", True)
    gap = since_correct(conn)
    assert gap[water][1] == 1 and gap[word_id(conn, "마시다")][1] == 1 and gap[book][1] == 0


def test_ungraded_answer_records_nothing(conn, fake):
    fake(sentence_json(), "not json")
    s = get_sentence(conn, 1)
    assert grade_sentence(conn, s["id"], "저는 주스 마셔요")["verdict"] == "ungraded"
    assert conn.execute("SELECT count(*) FROM sentence_word_verdicts").fetchone()[0] == 0
    assert grammar_answers(conn) == []


def test_grammar_points_are_real_curriculum_points():
    assert set(LESSON_ONE) <= set(grammar.curriculum()[0])
