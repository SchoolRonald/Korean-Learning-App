import json
import random
import sqlite3
from types import SimpleNamespace

import anthropic
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import llm, sentences
from app.db import connect, init_db
from app.drill import record_word_attempt
from app.learn import mark_learned
from app.sentences import focus_pool, focus_words, get_sentence, grade_sentence, prefetch, reference_variants


class FakeClient:
    """Stands in for anthropic.Anthropic(); returns queued replies in order."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []
        self.messages = self

    def create(self, **kwargs):
        self.requests.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        text, stop = (reply, "end_turn") if isinstance(reply, str) else reply
        return SimpleNamespace(
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(input_tokens=100, output_tokens=20),
            stop_reason=stop,
        )


def sentence_json(english="I drink water.", korean="저는 물을 마셔요.", bases=("저", "물", "마시다"), english_text=None):
    """A generation reply: one token per space-separated Korean word, with its dictionary form."""
    words = korean.rstrip(".").split()
    assert len(words) == len(bases)
    texts = english_text or [""] * len(words)
    tokens = [{"korean": w, "base": b, "english": f"<{b}>", "english_text": t} for w, b, t in zip(words, bases, texts)]
    return json.dumps({"english": english, "korean": korean, "tokens": tokens})


def verdict_json(verdict="almost", reason="Particle 을 is missing."):
    return json.dumps({"verdict": verdict, "reason": reason})


@pytest.fixture
def db_file(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_file):
    # A file, not :memory:, so the app's per-thread connections see the same data.
    c = connect(db_file)
    init_db(c)
    c.executemany(
        "INSERT INTO words (hangul, english, lesson) VALUES (?, ?, ?)",
        [("물", "water", 1), ("마시다", "to drink", 1), ("책", "book", 1), ("학교", "school", 2)],
    )
    c.execute("INSERT INTO learned (word_id, learned_at) SELECT id, '2026-10-01' FROM words")
    c.commit()
    return c


@pytest.fixture(autouse=True)
def few_words_ok(monkeypatch):
    monkeypatch.setattr(sentences, "MIN_LEARNED", 1)


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(llm, "usage", {"calls": 0, "input_tokens": 0, "output_tokens": 0})
    # Separate logger so tests do not write to llm_usage.log.
    monkeypatch.setattr(llm, "log", llm.logging.getLogger("gongbu_test_llm"))

    def install(*replies):
        client = FakeClient(*replies)
        monkeypatch.setattr(llm, "_client", client)
        return client

    return install


def word_id(conn, hangul):
    return conn.execute("SELECT id FROM words WHERE hangul = ?", (hangul,)).fetchone()[0]


def test_generate_stores_tokens_and_learned_word_ids(conn, fake):
    client = fake(sentence_json(english_text=["I", "water", "drink"]))
    s = get_sentence(conn, 1)
    assert s["source"] == "new" and s["english"] == "I drink water."
    row = conn.execute("SELECT korean_ref, word_ids FROM sentences WHERE id = ?", (s["id"],)).fetchone()
    assert row[0] == "저는 물을 마셔요."
    # 저 is not in the word list, so it is a new word and not one of the sentence's words.
    assert json.loads(row[1]) == sorted([word_id(conn, "물"), word_id(conn, "마시다")])
    assert [(t["korean"], t["new"]) for t in s["tokens"]] == [("저는", True), ("물을", False), ("마셔요", False)]
    # Meanings come from the word list when the word is in it, from the model otherwise.
    assert [t["english"] for t in s["tokens"]] == ["<저>", "water", "to drink"]
    assert s["tokens"][1]["english_text"] == "water"
    request = client.requests[0]
    assert request["model"] == "claude-haiku-5-5"
    assert "학교" not in request["messages"][0]["content"]  # lesson 2 word not offered


def test_same_spelling_picks_meaning_from_model(conn, fake):
    conn.executemany("INSERT INTO words (hangul, english, lesson) VALUES (?, ?, 1)",
                     [("저", "I, me (formal)"), ("저", "that (when something is far away)"), ("것", "thing")])
    conn.execute("INSERT OR IGNORE INTO learned (word_id, learned_at) SELECT id, '2026-10-01' FROM words")
    reply = {"english": "That is water.", "korean": "저 것은 물이에요.", "tokens": [
        {"korean": "저", "base": "저", "english": "that", "english_text": "That"},
        {"korean": "것은", "base": "것", "english": "thing", "english_text": ""},
        {"korean": "물이에요", "base": "물", "english": "water", "english_text": "water"},
    ]}
    fake(json.dumps(reply))
    s = get_sentence(conn, 1)
    assert s["tokens"][0]["english"] == "that (when something is far away)"


def test_unlearned_words_not_offered(conn, fake):
    conn.execute("DELETE FROM learned WHERE word_id = ?", (word_id(conn, "책"),))
    client = fake(sentence_json())
    get_sentence(conn, 1)
    assert "책 = book" not in client.requests[0]["messages"][0]["content"]


def test_too_many_new_words_rejected(conn, fake):
    # 물 is learned; 저, 커피, 고양이 and 주다 are not: 4 new words.
    fake(sentence_json("I give the cat water and coffee.", "저는 물과 커피를 고양이에게 줘요.", ["저", "물", "커피", "고양이", "주다"]))
    with pytest.raises(llm.LLMError, match="too many words"):
        get_sentence(conn, 1)


def test_tokens_that_do_not_spell_the_sentence_are_dropped(conn, fake):
    reply = json.loads(sentence_json())
    reply["tokens"][2]["korean"] = "먹어요"
    fake(json.dumps(reply))
    s = get_sentence(conn, 1)
    assert s["tokens"] is None  # no hints, but the sentence is still usable
    assert conn.execute("SELECT tokens FROM sentences").fetchone()[0] is None


def test_new_flags_follow_learning(conn, fake):
    conn.execute("INSERT INTO words (hangul, english, lesson) VALUES ('커피', 'coffee', 1)")
    fake(sentence_json("I drink coffee.", "커피를 마셔요.", ["커피", "마시다"]))
    first = get_sentence(conn, 1)
    assert [t["new"] for t in first["tokens"]] == [True, False]
    mark_learned(conn, word_id(conn, "커피"))
    again = get_sentence(conn, 1)
    assert again["id"] == first["id"] and [t["new"] for t in again["tokens"]] == [False, False]


def test_old_sentence_without_tokens_needs_all_words_learned(conn, fake):
    conn.execute("INSERT INTO words (hangul, english, lesson) VALUES ('커피', 'coffee', 1)")
    conn.execute(
        "INSERT INTO sentences (english, korean_ref, word_ids, created_at) VALUES (?, ?, ?, ?)",
        ("Coffee.", "커피요.", json.dumps([word_id(conn, "커피")]), "2026-10-01"),
    )
    fake(sentence_json())
    assert get_sentence(conn, 1)["source"] == "new"  # the old sentence is skipped
    mark_learned(conn, word_id(conn, "커피"))
    assert get_sentence(conn, 1)["english"] == "Coffee."


def test_migration_adds_tokens_column(tmp_path):
    old = sqlite3.connect(tmp_path / "old.db")
    old.execute("""CREATE TABLE sentences (id INTEGER PRIMARY KEY, english TEXT NOT NULL,
                   korean_ref TEXT NOT NULL, word_ids TEXT NOT NULL, created_at TEXT NOT NULL)""")
    old.execute("INSERT INTO sentences VALUES (1, 'Water.', '물이에요.', '[1]', '2026-10-01')")
    old.commit()
    init_db(old)
    init_db(old)  # running again is a no-op
    assert "tokens" in {r[1] for r in old.execute("PRAGMA table_info(sentences)")}
    assert old.execute("SELECT english, tokens FROM sentences").fetchone() == ("Water.", None)


def test_needs_enough_learned_words(conn, monkeypatch):
    monkeypatch.setattr(sentences, "MIN_LEARNED", 5)
    with pytest.raises(sentences.NotReady, match="Learn at least 5 words"):
        get_sentence(conn, 1)


def test_generate_matches_annotated_entries(conn, fake):
    conn.execute("INSERT INTO words (hangul, english, lesson) VALUES ('냄새 (나다)', 'smell', 1)")
    mark_learned(conn, word_id(conn, "냄새 (나다)"))
    fake(sentence_json("It smells.", "냄새가 나요.", ["냄새", "나다"]))
    s = get_sentence(conn, 1)
    ids = json.loads(conn.execute("SELECT word_ids FROM sentences WHERE id = ?", (s["id"],)).fetchone()[0])
    assert ids == [word_id(conn, "냄새 (나다)")]


def test_generate_rejects_sentence_with_no_known_words(conn, fake):
    fake(sentence_json("I like coffee.", "커피를 좋아해요.", ["커피", "좋아하다"]))
    with pytest.raises(llm.LLMError, match="unusable"):
        get_sentence(conn, 1)


def test_cached_unattempted_sentence_is_reused(conn, fake):
    client = fake(sentence_json())
    first = get_sentence(conn, 1)
    second = get_sentence(conn, 1)
    assert (second["id"], second["source"], second["reference"]) == (first["id"], "cache", "저는 물을 마셔요.")
    assert second["tokens"] == first["tokens"]
    assert len(client.requests) == 1


def test_cached_sentence_needs_all_words_in_lesson(conn, fake):
    conn.execute(
        "INSERT INTO sentences (english, korean_ref, word_ids, created_at) VALUES (?, ?, ?, ?)",
        ("I go to school.", "학교에 가요.", json.dumps([word_id(conn, "학교")]), "2026-10-01"),
    )
    fake(sentence_json())
    assert get_sentence(conn, 1)["source"] == "new"
    assert get_sentence(conn, 2)["english"] == "I go to school."


def test_falls_back_to_cache_when_llm_fails(conn, fake):
    fake(sentence_json(), anthropic.AnthropicError("boom"))
    first = get_sentence(conn, 1)
    grade_sentence(conn, first["id"], "저는 물을 마셔요")
    s = get_sentence(conn, 1)
    assert s["id"] == first["id"] and "Reusing a saved sentence" in s["note"]


def test_llm_failure_with_empty_cache_raises(conn, fake):
    fake(anthropic.AnthropicError("no key"))
    with pytest.raises(llm.LLMError, match="LLM unavailable"):
        get_sentence(conn, 1)


def test_missing_api_key_is_friendly_error(conn, fake, monkeypatch):
    no_key = SimpleNamespace(api_key=None, auth_token=None, credentials=None)
    monkeypatch.setattr(llm, "_client", None)
    monkeypatch.setattr(llm.anthropic, "Anthropic", lambda: no_key)
    with pytest.raises(llm.LLMError, match="ANTHROPIC_API_KEY"):
        get_sentence(conn, 1)


def test_exact_match_skips_llm(conn, fake):
    client = fake(sentence_json())
    s = get_sentence(conn, 1)
    r = grade_sentence(conn, s["id"], "저는  물을 마셔요")
    assert (r["verdict"], r["graded_by"]) == ("correct", "exact")
    assert len(client.requests) == 1
    assert tuple(conn.execute("SELECT kind, correct FROM attempts").fetchone()) == ("sentence", 1)


def test_llm_grade_recorded(conn, fake):
    fake(sentence_json(), verdict_json("almost", "Particle 을 is missing."))
    s = get_sentence(conn, 1)
    r = grade_sentence(conn, s["id"], "저는 물 마셔요")
    assert r == {"verdict": "almost", "reason": "Particle 을 is missing.",
                 "reference": "저는 물을 마셔요.", "graded_by": "llm"}
    assert tuple(conn.execute("SELECT answer, correct FROM attempts").fetchone()) == ("저는 물 마셔요", 0)


@pytest.mark.parametrize("reply", [
    "this is not json",
    '{"verdict": "great", "reason": "x"}',
    '{"verdict": "correct"}',
    '["correct", "fine"]',
    ('{"verdict": "corr', "max_tokens"),
    ("", "refusal"),
])
def test_bad_grader_output_is_ungraded_and_not_recorded(conn, fake, reply):
    fake(sentence_json(), reply)
    s = get_sentence(conn, 1)
    r = grade_sentence(conn, s["id"], "물")
    assert r["verdict"] == "ungraded" and r["graded_by"] is None and "reference" not in r
    assert conn.execute("SELECT count(*) FROM attempts").fetchone()[0] == 0


def test_prefetch_tops_up_to_two_waiting(conn, fake):
    client = fake(sentence_json(), sentence_json("I read a book.", "책을 읽어요.", ["책", "읽다"]))
    prefetch(conn, 1)
    prefetch(conn, 1)
    prefetch(conn, 1)  # already two waiting, no call
    assert len(client.requests) == 2
    assert conn.execute("SELECT count(*) FROM sentences").fetchone()[0] == 2


def test_prefetch_swallows_llm_errors(conn, fake):
    fake(anthropic.AnthropicError("down"))
    prefetch(conn, 1)
    assert conn.execute("SELECT count(*) FROM sentences").fetchone()[0] == 0


def test_call_cap(conn, fake, monkeypatch):
    monkeypatch.setattr(llm, "CALL_CAP", 1)
    client = fake(sentence_json())
    s = get_sentence(conn, 1)
    r = grade_sentence(conn, s["id"], "물")
    assert r["verdict"] == "ungraded" and "limit" in r["reason"]
    assert len(client.requests) == 1


def test_usage_is_counted(conn, fake):
    fake(sentence_json())
    get_sentence(conn, 1)
    assert llm.usage == {"calls": 1, "input_tokens": 100, "output_tokens": 20}


def test_focus_pool_prefers_highest_fail_rate(conn):
    record_word_attempt(conn, word_id(conn, "책"), "x", False)
    record_word_attempt(conn, word_id(conn, "물"), "x", False)
    record_word_attempt(conn, word_id(conn, "물"), "물", True)
    pool = [p[1] for p in focus_pool(conn, 1)]
    assert pool[:2] == ["책", "물"] and len(pool) == 3  # only 3 words at lesson 1


def test_focus_words_sampled_from_pool(conn, monkeypatch):
    pool = [(i, f"단어{i}", f"w{i}") for i in range(8)]
    monkeypatch.setattr(sentences, "focus_pool", lambda conn, max_lesson, topic_ids=None: pool)
    picks = {tuple(sorted(focus_words(conn, 1, random.Random(seed)))) for seed in range(20)}
    assert all(len(p) == 3 and set(p) <= set(pool) for p in picks)
    assert len(picks) > 1  # not the same three every time


def test_prompt_lists_earlier_sentences(conn, fake):
    client = fake(sentence_json(), sentence_json("I read a book.", "책을 읽어요.", ["책", "읽다"]))
    get_sentence(conn, 1)
    prefetch(conn, 1)
    assert "earlier sentences" not in client.requests[0]["messages"][0]["content"]
    assert "- I drink water." in client.requests[1]["messages"][0]["content"]


def test_duplicate_sentence_not_saved(conn, fake):
    fake(sentence_json(), sentence_json(english="i drink water."))
    get_sentence(conn, 1)
    prefetch(conn, 1)  # model repeats itself; logged and skipped
    assert conn.execute("SELECT count(*) FROM sentences").fetchone()[0] == 1


@pytest.fixture
def client(conn, db_file, monkeypatch):
    monkeypatch.setattr(main, "db_path", db_file)
    with TestClient(main.app) as c:
        yield c


def test_api_sentence_flow(client, fake, conn):
    fake(
        sentence_json(),
        sentence_json("I read a book.", "책을 읽어요.", ["책", "읽다"]),
        verdict_json("incorrect", "Wrong verb."),
        sentence_json("Water.", "물이에요.", ["물"]),  # prefetch after the second request
    )
    s = client.get("/api/sentence", params={"lesson": 1}).json()
    assert s["reference"] == "저는 물을 마셔요." and s["llm"] == {"calls": 1, "cap": llm.CALL_CAP}
    # The response also queued a background prefetch of the next sentence.
    assert conn.execute("SELECT count(*) FROM sentences").fetchone()[0] == 2
    r = client.post("/api/sentence/answer", json={"sentence_id": s["id"], "answer": "물을 먹어요"}).json()
    assert r["verdict"] == "incorrect" and r["graded_by"] == "llm"
    nxt = client.get("/api/sentence", params={"lesson": 1, "exclude": s["id"]}).json()
    assert (nxt["english"], nxt["source"]) == ("I read a book.", "cache")


def test_api_sentence_llm_error_is_503(client, fake):
    fake(anthropic.AnthropicError("no key"))
    res = client.get("/api/sentence", params={"lesson": 1})
    assert res.status_code == 503 and "LLM unavailable" in res.json()["detail"]


def test_api_sentence_not_ready_is_404(client, monkeypatch):
    monkeypatch.setattr(sentences, "MIN_LEARNED", 50)
    res = client.get("/api/sentence", params={"lesson": 1})
    assert res.status_code == 404 and "Learn tab" in res.json()["detail"]


def test_sentences_page_served(client):
    assert "Sentence practice" in client.get("/sentences").text
    assert client.get("/static/common.js").status_code == 200


def tok(korean, base, english):
    return {"korean": korean, "base": base, "english": english}


@pytest.mark.parametrize("reference, tokens, expected", [
    ("저 남자는 학생이에요.", [tok("저", "저", "that (when something is far away)"), tok("남자는", "남자", "man"), tok("학생이에요", "학생", "student")],
     ["저 남자는 학생이에요.", "그 남자는 학생이에요."]),
    ("저는 학생이에요.", [tok("저는", "저", "I, me (formal)"), tok("학생이에요", "학생", "student")],
     ["저는 학생이에요."]),  # 저 as "I" is not a demonstrative
    ("그는 학생이에요.", [tok("그는", "그", "he, him"), tok("학생이에요", "학생", "student")],
     ["그는 학생이에요."]),  # nor 그 as "he"
    ("저기에 가요.", [tok("저기에", "저기", "there (when farther away)"), tok("가요", "가다", "to go")],
     ["저기에 가요.", "거기에 가요."]),
    ("저건 그 책이에요.", [tok("저건", "저것", "that (thing)"), tok("그", "그", "that"), tok("책이에요", "책", "book")],
     ["저건 그 책이에요.", "저건 저 책이에요.", "그건 그 책이에요.", "그건 저 책이에요."]),
    ("저 남자요.", None, ["저 남자요."]),  # no tokens, no variants
])
def test_reference_variants(reference, tokens, expected):
    assert reference_variants(reference, tokens) == expected


def test_either_demonstrative_is_correct_without_llm(conn, fake):
    conn.executemany("INSERT INTO words (hangul, english, lesson) VALUES (?, ?, 1)",
                     [("저", "that (when something is far away)"), ("남자", "man")])
    conn.execute("INSERT OR IGNORE INTO learned (word_id, learned_at) SELECT id, '2026-10-01' FROM words")
    client = fake(sentence_json("That man drinks water.", "저 남자는 물을 마셔요.", ["저", "남자", "물", "마시다"]))
    s = get_sentence(conn, 1)
    r = grade_sentence(conn, s["id"], "그 남자는 물을 마셔요")
    assert (r["verdict"], r["graded_by"]) == ("correct", "exact") and "그 and 저" in r["reason"]
    assert len(client.requests) == 1  # generation only, no grading call


def test_grader_told_both_demonstratives_are_fine(conn, fake):
    client = fake(sentence_json(), verdict_json())
    s = get_sentence(conn, 1)
    grade_sentence(conn, s["id"], "물")
    assert "그, 거기" in client.requests[1]["system"] and "accept either" in client.requests[1]["system"]


def name_reply(tokens, english="Minho drinks water.", korean="민호는 물을 마셔요."):
    return json.dumps({"english": english, "korean": korean, "tokens": [
        {"korean": k, "base": b, "english": e, "english_text": t, "is_name": n} for k, b, e, t, n in tokens
    ]})


def test_name_is_not_a_new_word(conn, fake):
    fake(name_reply([
        ("민호는", "민호", "Minho", "Minho", True),
        ("물을", "물", "water", "water", False),
        ("마셔요", "마시다", "to drink", "drinks", False),
    ]))
    s = get_sentence(conn, 1)
    minho = s["tokens"][0]
    assert (minho["name"], minho["new"], minho["english"], minho["word_id"]) == (True, False, "Minho", None)
    # Names never become vocabulary: no word, no stats.
    assert conn.execute("SELECT count(*) FROM words WHERE hangul = '민호'").fetchone()[0] == 0


def test_names_do_not_count_toward_new_word_limit(conn, fake):
    # 2 unlearned words (저, 커피) is the limit; the name on top must not push it over.
    fake(name_reply([
        ("저는", "저", "I", "I", False),
        ("민호에게", "민호", "Minho", "Minho", True),
        ("물과", "물", "water", "water", False),
        ("커피를", "커피", "coffee", "coffee", False),
        ("줘요", "주다", "to give", "give", False),
    ], english="I give Minho water and coffee.", korean="저는 민호에게 물과 커피를 줘요."))
    with pytest.raises(llm.LLMError, match="too many words"):
        get_sentence(conn, 1)  # 저, 커피, 주다 are 3 new words; the name is not counted
    conn.execute("INSERT INTO words (hangul, english, lesson) VALUES ('주다', 'to give', 1)")
    mark_learned(conn, word_id(conn, "주다"))
    fake(name_reply([
        ("저는", "저", "I", "I", False),
        ("민호에게", "민호", "Minho", "Minho", True),
        ("물과", "물", "water", "water", False),
        ("커피를", "커피", "coffee", "coffee", False),
        ("줘요", "주다", "to give", "give", False),
    ], english="I give Minho water and coffee.", korean="저는 민호에게 물과 커피를 줘요."))
    s = get_sentence(conn, 1)
    assert [t["korean"] for t in s["tokens"] if t["new"]] == ["저는", "커피를"]


def test_list_word_cannot_be_called_a_name(conn, fake):
    fake(name_reply([
        ("물을", "물", "water", "water", True),  # model wrongly says name
        ("마셔요", "마시다", "to drink", "drink", False),
    ], english="I drink water.", korean="물을 마셔요."))
    s = get_sentence(conn, 1)
    assert s["tokens"][0]["name"] is False and s["tokens"][0]["english"] == "water"


def test_tokens_saved_before_names_existed(conn, fake):
    conn.execute(
        "INSERT INTO sentences (english, korean_ref, word_ids, tokens, created_at) VALUES (?, ?, ?, ?, ?)",
        ("Water.", "물이에요.", json.dumps([word_id(conn, "물")]),
         json.dumps([{"korean": "물이에요", "base": "물", "english": "water", "english_text": "Water", "word_id": word_id(conn, "물")}]),
         "2026-10-01"),
    )
    s = get_sentence(conn, 1)
    assert s["tokens"][0]["name"] is False and s["tokens"][0]["new"] is False


def test_copula_stripped_from_base(conn, fake):
    conn.execute("INSERT INTO words (hangul, english, lesson) VALUES ('뭐', 'what', 22)")
    fake(name_reply([
        ("물이", "물", "water", "water", False),
        ("뭐예요", "뭐예요", "what is", "What is", False),
    ], english="What is water?", korean="물이 뭐예요?"))
    s = get_sentence(conn, 22)
    what = s["tokens"][1]
    # Matched to the list's 뭐 (unlearned, so new), with the list's meaning.
    assert (what["base"], what["english"], what["english_text"], what["new"]) == ("뭐", "what", "What", True)


def test_copula_stripped_when_word_not_in_list(conn, fake):
    fake(name_reply([
        ("물이", "물", "water", "water", False),
        ("뭐예요", "뭐예요", "what is", "What is", False),
    ], english="What is water?", korean="물이 뭐예요?"))
    what = get_sentence(conn, 1)["tokens"][1]
    assert (what["base"], what["english"], what["word_id"]) == ("뭐", "what", None)


def test_word_ending_like_copula_kept_when_in_list(conn, fake):
    conn.execute("INSERT INTO words (hangul, english, lesson) VALUES ('아니에요', 'no (polite)', 1)")
    mark_learned(conn, word_id(conn, "아니에요"))
    fake(name_reply([("아니에요", "아니에요", "no", "No", False)], english="No.", korean="아니에요."))
    assert get_sentence(conn, 1)["tokens"][0]["base"] == "아니에요"
