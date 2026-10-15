import argparse
import csv
import re
import unicodedata

from app.db import connect, init_db

# Placeholder header names until we inspect a real howtostudykorean CSV.
DEFAULT_MAPPING = {"hangul": "Korean", "english": "English", "lesson": "Lesson"}


def parse_lesson(value):
    match = re.search(r"\d+", value or "")
    return int(match.group()) if match else None


def load_csv(conn, path, mapping=DEFAULT_MAPPING, lesson=None):
    """Load words from a CSV into the words table. Returns the number of rows inserted."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        required = [mapping["hangul"], mapping["english"]]
        lesson_col = mapping.get("lesson")
        if lesson is None:
            required.append(lesson_col)
        missing = [c for c in required if c not in headers]
        if missing:
            raise ValueError(f"Missing columns {missing}; CSV has {headers}")
        use_lesson_col = lesson_col in headers

        rows = []
        for line_no, row in enumerate(reader, start=2):
            hangul = unicodedata.normalize("NFC", (row.get(mapping["hangul"]) or "").strip())
            english = (row.get(mapping["english"]) or "").strip()
            if not hangul or not english:
                continue
            row_lesson = parse_lesson(row.get(lesson_col)) if use_lesson_col else None
            if row_lesson is None:
                row_lesson = lesson
            if row_lesson is None:
                raise ValueError(f"Line {line_no}: no lesson number and no --lesson given")
            rows.append((hangul, english, row_lesson))

    before = conn.total_changes
    conn.executemany(
        "INSERT OR IGNORE INTO words (hangul, english, lesson) VALUES (?, ?, ?)", rows
    )
    conn.commit()
    return conn.total_changes - before


def main():
    p = argparse.ArgumentParser(description="Load a vocab CSV into the database.")
    p.add_argument("path")
    p.add_argument("--hangul", default=DEFAULT_MAPPING["hangul"], help="Korean column name")
    p.add_argument("--english", default=DEFAULT_MAPPING["english"], help="English column name")
    p.add_argument("--lesson-col", default=DEFAULT_MAPPING["lesson"], help="lesson column name")
    p.add_argument("--lesson", type=int, help="lesson number for rows without one")
    p.add_argument("--db", help="database path (default: GONGBU_DB or gongbu.db)")
    args = p.parse_args()

    with open(args.path, encoding="utf-8-sig", newline="") as f:
        print("Columns found:", next(csv.reader(f), []))

    conn = connect(args.db)
    init_db(conn)
    mapping = {"hangul": args.hangul, "english": args.english, "lesson": args.lesson_col}
    try:
        n = load_csv(conn, args.path, mapping, args.lesson)
    except ValueError as e:
        raise SystemExit(f"Error: {e}")
    print(f"Inserted {n} words")


if __name__ == "__main__":
    main()
