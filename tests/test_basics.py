import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main

HANGUL = json.loads((Path(__file__).resolve().parent.parent / "static" / "hangul.json").read_text(encoding="utf-8"))
LETTERS = [letter for group in HANGUL["letters"] for letter in group["letters"]]
KEYS = {key["code"]: key for row in HANGUL["keyboard"] for key in row}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "db_path", tmp_path / "test.db")
    with TestClient(main.app) as c:
        yield c


def test_basics_page_served(client):
    assert "Basics and Introduction" in client.get("/basics").text
    assert client.get("/static/hangul.json").json() == HANGUL


def test_every_tab_links_to_basics(client):
    for page in ["/", "/basics", "/words", "/sentences", "/stats"]:
        nav = client.get(page).text.split("</p>")[0]
        assert "Basics and Introduction" in nav, page


def test_letter_groups():
    assert [len(g["letters"]) for g in HANGUL["letters"]] == [14, 5, 10, 11]
    assert len({letter["char"] for letter in LETTERS}) == 40


def test_letter_fields():
    for letter in LETTERS:
        assert all(letter[f] for f in ("char", "name", "roman", "keys")), letter
        assert letter["example"]["word"] and letter["example"]["english"], letter


def test_romanizations_unique():
    # The sound quiz shows the romanization, so each one must point at one letter.
    romans = [letter["roman"] for letter in LETTERS]
    assert len(set(romans)) == len(romans)


def test_keys_exist_and_match():
    for letter in LETTERS:
        for k in letter["keys"]:
            shift = k.startswith("Shift+")
            key = KEYS[k.removeprefix("Shift+")]
            if shift:
                assert key["shift"], k
        if len(letter["keys"]) == 1:
            k = letter["keys"][0]
            key = KEYS[k.removeprefix("Shift+")]
            assert key["shift" if k.startswith("Shift+") else "char"] == letter["char"], letter["char"]


def test_keyboard_covers_layout():
    assert [len(row) for row in HANGUL["keyboard"]] == [10, 9, 7]
    # Every key's letter, and every Shift letter, is in the alphabet chart.
    chars = {letter["char"] for letter in LETTERS}
    for key in KEYS.values():
        assert key["char"] in chars
        assert key["shift"] is None or key["shift"] in chars
