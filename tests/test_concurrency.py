from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.db import connect, init_db


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    c = connect(path)
    init_db(c)
    c.executemany("INSERT INTO words (hangul, english, lesson) VALUES (?, ?, 1)", [(f"단어{i}", f"w{i}") for i in range(30)])
    c.commit()
    monkeypatch.setattr(main, "db_path", path)
    with TestClient(main.app) as client:
        yield client


def test_concurrent_requests(client):
    """The Learn page sends its "done" requests all at once; they must not share one connection."""
    ids = list(range(1, 31))

    def done(word_id):
        return client.post("/api/learn/done", json={"word_id": word_id}).status_code

    with ThreadPoolExecutor(max_workers=10) as pool:
        codes = list(pool.map(done, ids * 5))
    assert codes == [200] * len(codes)
    assert client.get("/api/stats", params={"lesson": 1}).json()["learned"] == 30
