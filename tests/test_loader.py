import sqlite3
import unicodedata

import pytest

from app.db import init_db
from app.loader import load_csv


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    init_db(c)
    return c


def write_csv(tmp_path, text, encoding="utf-8"):
    path = tmp_path / "vocab.csv"
    path.write_text(text, encoding=encoding)
    return path


def all_words(conn):
    return conn.execute("SELECT hangul, english, lesson FROM words ORDER BY id").fetchall()


def test_default_mapping(conn, tmp_path):
    path = write_csv(tmp_path, "Korean,English,Lesson\n사과,apple,1\n물,water,2\n")
    assert load_csv(conn, path) == 2
    assert all_words(conn) == [("사과", "apple", 1), ("물", "water", 2)]


def test_custom_mapping(conn, tmp_path):
    path = write_csv(tmp_path, "word,meaning,unit\n책,book,4\n")
    mapping = {"hangul": "word", "english": "meaning", "lesson": "unit"}
    assert load_csv(conn, path, mapping) == 1
    assert all_words(conn) == [("책", "book", 4)]


def test_constant_lesson_without_column(conn, tmp_path):
    path = write_csv(tmp_path, "Korean,English\n학교,school\n")
    assert load_csv(conn, path, lesson=7) == 1
    assert all_words(conn) == [("학교", "school", 7)]


def test_lesson_text_is_parsed(conn, tmp_path):
    path = write_csv(tmp_path, "Korean,English,Lesson\n집,house,Lesson 3\n")
    load_csv(conn, path)
    assert all_words(conn) == [("집", "house", 3)]


def test_bom_is_stripped(conn, tmp_path):
    path = write_csv(tmp_path, "Korean,English,Lesson\n개,dog,1\n", encoding="utf-8-sig")
    assert load_csv(conn, path) == 1


def test_blank_rows_skipped(conn, tmp_path):
    path = write_csv(tmp_path, "Korean,English,Lesson\n개,dog,1\n,,\n , ,2\n고양이,cat,1\n")
    assert load_csv(conn, path) == 2


def test_reload_is_idempotent(conn, tmp_path):
    path = write_csv(tmp_path, "Korean,English,Lesson\n개,dog,1\n")
    assert load_csv(conn, path) == 1
    assert load_csv(conn, path) == 0
    assert len(all_words(conn)) == 1


def test_missing_column_raises(conn, tmp_path):
    path = write_csv(tmp_path, "Hangul,English,Lesson\n개,dog,1\n")
    with pytest.raises(ValueError, match="Hangul"):
        load_csv(conn, path)


def test_missing_lesson_value_raises(conn, tmp_path):
    path = write_csv(tmp_path, "Korean,English,Lesson\n개,dog,\n")
    with pytest.raises(ValueError, match="Line 2"):
        load_csv(conn, path)


def test_hangul_stored_as_nfc(conn, tmp_path):
    decomposed = unicodedata.normalize("NFD", "한국")
    path = write_csv(tmp_path, f"Korean,English,Lesson\n{decomposed},Korea,1\n")
    load_csv(conn, path)
    assert all_words(conn)[0][0] == "한국"
