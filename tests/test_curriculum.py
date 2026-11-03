import json
import re
import shutil
from pathlib import Path

import pytest

from app import curriculum, krdict

GRAMMAR = Path(__file__).resolve().parent.parent / "grammar"

SEARCH_XML = """<?xml version="1.0" encoding="UTF-8"?>
<channel><total>3</total>
<item><target_code>2</target_code><word>이</word><sup_no>2</sup_no><pos>조사</pos></item>
<item><target_code>1</target_code><word>이</word><sup_no>1</sup_no><pos>명사</pos></item>
<item><target_code>3</target_code><word>이것</word><sup_no>0</sup_no><pos>대명사</pos></item>
</channel>"""


def view_xml(code, word, pos, english="eun"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<channel><item><target_code>{code}</target_code><word_info>
<word>{word}</word><pos>{pos}</pos>
<sense_info><definition>조사.</definition>
<translation><trans_lang> 영어 </trans_lang><trans_word><![CDATA[{english}]]></trans_word>
<trans_dfn><![CDATA[A particle used to mark the topic.]]></trans_dfn></translation>
<reference>받침 있는 명사 뒤에 붙여 쓴다.</reference>
<example_info><type>문장</type><example>오늘은   더워요.</example></example_info>
<example_info><type>대화</type><example>가:  뭐 해?</example></example_info>
<example_info><type>구</type><example>책은</example></example_info>
</sense_info></word_info></item></channel>"""


def test_parse_search():
    results = krdict.parse_search(SEARCH_XML)
    assert [r["target_code"] for r in results] == ["2", "1", "3"]
    assert results[0] == {"target_code": "2", "word": "이", "pos": "조사", "sup_no": 2}


def test_parse_view_keeps_sentence_and_phrase_examples():
    entry = krdict.parse_view(view_xml("86111", "은", "조사"))
    assert entry["url"].endswith("ParaWordNo=86111")
    sense = entry["senses"][0]
    assert sense["english_definition"] == "A particle used to mark the topic."
    assert sense["note"] == "받침 있는 명사 뒤에 붙여 쓴다."
    assert sense["examples"] == ["오늘은 더워요.", "책은"]


def test_error_response_raises():
    with pytest.raises(krdict.KrdictError, match="010"):
        krdict.parse_search("<error><error_code>010</error_code><message>limit</message></error>")


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("KRDICT_API_KEY", raising=False)
    with pytest.raises(krdict.KrdictError, match="KRDICT_API_KEY"):
        krdict.fetch("search", {"q": "은"})


def test_lookup_matches_exact_word_and_pos():
    calls = []

    def get(endpoint, params):
        calls.append((endpoint, params["q"]))
        return SEARCH_XML if endpoint == "search" else view_xml(params["q"], "이", "조사")

    entries = krdict.lookup("이", "조사", get)
    assert [e["target_code"] for e in entries] == ["2"]
    assert ("view", "1") not in calls and ("view", "3") not in calls


def test_lookup_treats_no_pos_as_pattern_and_falls_back():
    search = """<channel>
<item><target_code>7</target_code><word>-어지다</word><sup_no>0</sup_no><pos>품사 없음</pos></item>
<item><target_code>8</target_code><word>-고</word><sup_no>1</sup_no><pos>어미</pos></item>
</channel>"""

    def get(endpoint, params):
        return search if endpoint == "search" else view_xml(params["q"], "x", "")

    assert [e["target_code"] for e in krdict.lookup("-어지다", "", get)] == ["7"]
    assert [e["target_code"] for e in krdict.lookup("-고", "조사", get)] == ["8"]


class FakeAI:
    def __init__(self, splits, reject=()):
        self.splits = splits
        self.reject = set(reject)
        self.calls = []

    def __call__(self, purpose, system, prompt, schema, **kwargs):
        self.calls.append(purpose)
        if purpose == "curriculum-split":
            lesson = int(prompt.split()[1])
            return {"points": self.splits[lesson]}
        summaries = []
        for block in prompt.split("\n\n"):
            point_id = block[1:].split("]")[0]
            codes = [c for c in re.findall(r"\{(\d+)\}", block) if c not in self.reject]
            summaries.append({"id": point_id, "sources": codes, "summary": f"Summary of {point_id}."})
        return {"summaries": summaries}


def fake_get(endpoint, params):
    if endpoint == "search":
        word = params["q"]
        return f"<channel><item><target_code>{len(word)}{ord(word[-1])}</target_code><word>{word}</word><sup_no>0</sup_no><pos>조사</pos></item></channel>"
    return view_xml(params["q"], "는", "조사")


def point(pid, related=(), lookups=()):
    return {"id": pid, "title": pid.title(), "pattern": "N + 는", "kind": "particle",
            "related": list(related), "lookups": [{"headword": h, "pos": "조사"} for h in lookups]}


@pytest.fixture
def grammar_dir(tmp_path):
    shutil.copy(GRAMMAR / "htsk_lessons.json", tmp_path / "htsk_lessons.json")
    return tmp_path


def test_build_writes_files_and_links_related(grammar_dir):
    ai = FakeAI({
        1: [point("topic", lookups=["는"]), point("Topic", related=["subject"])],
        2: [point("subject", related=["topic", "missing"], lookups=["가"])],
    })
    curriculum.build([1, 2], grammar_dir, ai, fake_get, report=lambda _: None)
    data = json.loads((grammar_dir / "curriculum.json").read_text(encoding="utf-8"))["points"]
    by_id = {p["id"]: p for p in data}
    assert list(by_id) == ["topic", "topic-2", "subject"]
    assert by_id["subject"]["related"] == ["topic"]
    assert by_id["topic"]["related"] == ["subject"]
    assert by_id["topic-2"]["related"] == []
    assert by_id["topic"]["summary"] == "Summary of topic."
    sources = json.loads((grammar_dir / "sources.json").read_text(encoding="utf-8"))
    assert sources["license"] == krdict.LICENSE
    assert set(sources["entries"]) == {c for p in data for c in p["sources"]}
    assert ai.calls == ["curriculum-split", "curriculum-summary"] * 2


def test_build_drops_sources_the_ai_does_not_choose(grammar_dir):
    neun_code = f"1{ord('는')}"
    ai = FakeAI({1: [point("topic", lookups=["는", "은"])]}, reject={neun_code})
    curriculum.build([1], grammar_dir, ai, fake_get, report=lambda _: None)
    points, sources = curriculum.load(grammar_dir)
    assert points[0]["sources"] == [f"1{ord('은')}"]
    assert neun_code not in sources


def test_summary_asks_again_for_missing_points(grammar_dir):
    class ForgetfulAI(FakeAI):
        def __call__(self, purpose, system, prompt, schema, **kwargs):
            data = super().__call__(purpose, system, prompt, schema, **kwargs)
            if purpose == "curriculum-summary" and self.calls.count(purpose) == 1:
                data["summaries"] = data["summaries"][:1]
            return data

    ai = ForgetfulAI({1: [point("topic"), point("subject")]})
    curriculum.build([1], grammar_dir, ai, fake_get, report=lambda _: None)
    assert [p["summary"] for p in curriculum.load(grammar_dir)[0]] == ["Summary of topic.", "Summary of subject."]
    assert ai.calls.count("curriculum-summary") == 2


def test_build_skips_built_lessons(grammar_dir):
    ai = FakeAI({1: [point("topic")], 2: [point("subject")]})
    curriculum.build([1], grammar_dir, ai, fake_get, report=lambda _: None)
    curriculum.build([1, 2], grammar_dir, ai, fake_get, report=lambda _: None)
    assert ai.calls.count("curriculum-split") == 2


def test_refresh_regrounds_without_splitting(grammar_dir):
    eun_code = f"1{ord('은')}"
    curriculum.build([1], grammar_dir, FakeAI({1: [point("topic", lookups=["은"])]}, reject={eun_code}),
                     fake_get, report=lambda _: None)
    assert curriculum.load(grammar_dir)[0][0]["sources"] == []
    ai = FakeAI({})
    curriculum.build([1], grammar_dir, ai, fake_get, report=lambda _: None, refresh=True)
    points, _ = curriculum.load(grammar_dir)
    assert ai.calls == ["curriculum-summary"]
    assert points[0]["sources"] == [eun_code]
    assert points[0]["lookups"] == [{"headword": "은", "pos": "조사"}]


def test_build_rejects_lessons_without_topics(grammar_dir):
    with pytest.raises(curriculum.CurriculumError, match="99"):
        curriculum.build([99], grammar_dir, FakeAI({}), fake_get)


def test_parse_lessons():
    assert curriculum.parse_lessons("1-3,5") == [1, 2, 3, 5]


@pytest.mark.skipif(not (GRAMMAR / "curriculum.json").exists(), reason="curriculum not built")
def test_committed_curriculum_is_complete():
    points, sources = curriculum.load(GRAMMAR)
    ids = [p["id"] for p in points]
    assert len(ids) == len(set(ids))
    assert {p["lesson"] for p in points} == set(range(1, 26))
    for p in points:
        assert p["kind"] in curriculum.KINDS, p["id"]
        assert p["title"] and p["pattern"] and p["summary"], p["id"]
        assert all(look["headword"] for look in p["lookups"]), p["id"]
        assert set(p["related"]) <= set(ids), p["id"]
        for code in p["sources"]:
            assert sources[code]["url"].startswith("https://krdict.korean.go.kr/"), code
            assert sources[code]["senses"], code
