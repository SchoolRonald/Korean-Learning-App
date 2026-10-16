import argparse
import csv
import re
import unicodedata

from app.db import connect, init_db

# howtostudykorean lists have no header row: hangul, english, lesson tag like "Unit1_Lesson25".
# A mapping holds column numbers for headerless files, or column names for files with a header.
DEFAULT_MAPPING = {"hangul": 0, "english": 1, "lesson": 2}


def parse_lesson(value):
    # Last number, so "Unit1_Lesson25" is lesson 25 (lessons are numbered across units).
    numbers = re.findall(r"\d+", value or "")
    return int(numbers[-1]) if numbers else None


def resolve_columns(mapping, rows, lesson):
    """Turn the mapping into column indexes. Removes the header row when columns are named."""
    keys = ["hangul", "english"] + ([] if lesson is not None else ["lesson"])
    values = [mapping.get(k) for k in ("hangul", "english", "lesson")]
    if all(isinstance(v, int) or v is None for v in values):
        width = len(rows[0]) if rows else 0
        missing = [mapping[k] for k in keys if mapping[k] >= width]
        if missing:
            raise ValueError(f"Missing columns {missing}; first row has {width} columns: {rows[0] if rows else []}")
        lesson_col = mapping.get("lesson")
        return mapping["hangul"], mapping["english"], lesson_col if lesson_col is not None and lesson_col < width else None, 1
    if not all(isinstance(v, str) or v is None for v in values):
        raise ValueError("Use either all column names or all column numbers in the mapping")
    header = rows.pop(0) if rows else []
    missing = [mapping[k] for k in keys if mapping[k] not in header]
    if missing:
        raise ValueError(f"Missing columns {missing}; CSV has {header}")
    lesson_col = header.index(mapping["lesson"]) if mapping.get("lesson") in header else None
    return header.index(mapping["hangul"]), header.index(mapping["english"]), lesson_col, 2


def load_csv(conn, path, mapping=DEFAULT_MAPPING, lesson=None):
    """Load words from a CSV into the words table. Returns the number of rows inserted."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        lines = list(csv.reader(f))
    h_col, e_col, l_col, first_line = resolve_columns(mapping, lines, lesson)

    def cell(row, col):
        return row[col].strip() if col is not None and col < len(row) else ""

    rows = []
    for line_no, row in enumerate(lines, start=first_line):
        hangul = unicodedata.normalize("NFC", cell(row, h_col))
        english = cell(row, e_col)
        if not hangul or not english:
            continue
        row_lesson = parse_lesson(cell(row, l_col))
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


def column(value):
    return int(value) if value.isdigit() else value


def main():
    p = argparse.ArgumentParser(description="Load a vocab CSV into the database.")
    p.add_argument("path")
    p.add_argument("--hangul", default="0", help="Korean column: number (no header) or name (header row)")
    p.add_argument("--english", default="1", help="English column: number or name")
    p.add_argument("--lesson-col", default="2", help="lesson column: number or name")
    p.add_argument("--lesson", type=int, help="lesson number for rows without one")
    p.add_argument("--db", help="database path (default: GONGBU_DB or gongbu.db)")
    args = p.parse_args()

    with open(args.path, encoding="utf-8-sig", newline="") as f:
        print("First row:", next(csv.reader(f), []))

    conn = connect(args.db)
    init_db(conn)
    mapping = {"hangul": column(args.hangul), "english": column(args.english), "lesson": column(args.lesson_col)}
    try:
        n = load_csv(conn, args.path, mapping, args.lesson)
    except ValueError as e:
        raise SystemExit(f"Error: {e}")
    print(f"Inserted {n} words")


if __name__ == "__main__":
    main()
