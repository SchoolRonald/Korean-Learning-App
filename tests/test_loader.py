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


NAMED = {"hangul": "Korean", "english": "English", "lesson": "Lesson"}


def all_words(conn):
    return conn.execute("SELECT hangul, english, lesson FROM words ORDER BY id").fetchall()


def test_named_columns(conn, tmp_path):
    path = write_csv(tmp_path, "Korean,English,Lesson\n사과,apple,1\n물,water,2\n")
    assert load_csv(conn, path, NAMED) == 2
    assert all_words(conn) == [("사과", "apple", 1), ("물", "water", 2)]


def test_custom_mapping(conn, tmp_path):
    path = write_csv(tmp_path, "word,meaning,unit\n책,book,4\n")
    mapping = {"hangul": "word", "english": "meaning", "lesson": "unit"}
    assert load_csv(conn, path, mapping) == 1
    assert all_words(conn) == [("책", "book", 4)]


def test_constant_lesson_without_column(conn, tmp_path):
    path = write_csv(tmp_path, "Korean,English\n학교,school\n")
    assert load_csv(conn, path, NAMED, lesson=7) == 1
    assert all_words(conn) == [("학교", "school", 7)]


def test_lesson_text_is_parsed(conn, tmp_path):
    path = write_csv(tmp_path, "Korean,English,Lesson\n집,house,Lesson 3\n")
    load_csv(conn, path, NAMED)
    assert all_words(conn) == [("집", "house", 3)]


def test_bom_is_stripped(conn, tmp_path):
    path = write_csv(tmp_path, "Korean,English,Lesson\n개,dog,1\n", encoding="utf-8-sig")
    assert load_csv(conn, path, NAMED) == 1


def test_blank_rows_skipped(conn, tmp_path):
    path = write_csv(tmp_path, "Korean,English,Lesson\n개,dog,1\n,,\n , ,2\n고양이,cat,1\n")
    assert load_csv(conn, path, NAMED) == 2


def test_reload_is_idempotent(conn, tmp_path):
    path = write_csv(tmp_path, "Korean,English,Lesson\n개,dog,1\n")
    assert load_csv(conn, path, NAMED) == 1
    assert load_csv(conn, path, NAMED) == 0
    assert len(all_words(conn)) == 1


def test_missing_column_raises(conn, tmp_path):
    path = write_csv(tmp_path, "Hangul,English,Lesson\n개,dog,1\n")
    with pytest.raises(ValueError, match="Hangul"):
        load_csv(conn, path, NAMED)


def test_missing_lesson_value_raises(conn, tmp_path):
    path = write_csv(tmp_path, "Korean,English,Lesson\n개,dog,\n")
    with pytest.raises(ValueError, match="Line 2"):
        load_csv(conn, path, NAMED)


def test_hangul_stored_as_nfc(conn, tmp_path):
    decomposed = unicodedata.normalize("NFD", "한국")
    path = write_csv(tmp_path, f"Korean,English,Lesson\n{decomposed},Korea,1\n")
    load_csv(conn, path, NAMED)
    assert all_words(conn)[0][0] == "한국"


def test_default_is_howtostudykorean_format(conn, tmp_path):
    path = write_csv(tmp_path, '한국,Korea,Unit1_Lesson1\n저,"I, me (formal)",Unit1_Lesson1\n이때,at this moment,Unit1_Lesson25')
    assert load_csv(conn, path) == 3
    assert all_words(conn) == [("한국", "Korea", 1), ("저", "I, me (formal)", 1), ("이때", "at this moment", 25)]


def test_lesson_tag_uses_last_number(conn, tmp_path):
    path = write_csv(tmp_path, "개,dog,Unit2_Lesson31\n")
    load_csv(conn, path)
    assert all_words(conn) == [("개", "dog", 31)]


def test_column_number_out_of_range(conn, tmp_path):
    path = write_csv(tmp_path, "개,dog\n")
    with pytest.raises(ValueError, match="2 columns"):
        load_csv(conn, path)
    assert load_csv(conn, path, lesson=1) == 1  # fine when the lesson is given


def test_mixed_mapping_rejected(conn, tmp_path):
    path = write_csv(tmp_path, "Korean,English,Lesson\n개,dog,1\n")
    with pytest.raises(ValueError, match="all column names or all column numbers"):
        load_csv(conn, path, {"hangul": "Korean", "english": 1, "lesson": 2})
