import datetime
from fastapi.testclient import TestClient
from app.database import init_db, engine, Base, SessionLocal
from app.models import Album
from app.queue_logic import initialize_queue
from app import daily


def setup_module(module):
    Base.metadata.drop_all(bind=engine)
    init_db()
    with SessionLocal() as s:
        s.add(Album(title="Kind of Blue", artist="Miles Davis", year=1959, genre="Jazz"))
        s.add(Album(title="Thriller", artist="Michael Jackson", year=1982, genre="Pop"))
        s.commit()
        initialize_queue(s)


def _client():
    from app.main import app
    return TestClient(app)


def test_home_returns_200():
    r = _client().get("/")
    assert r.status_code == 200


def test_albums_page_lists_and_filters():
    c = _client()
    r = c.get("/albums")
    assert r.status_code == 200
    assert "Kind of Blue" in r.text
    r2 = c.get("/albums", params={"genre": "Pop"})
    assert "Thriller" in r2.text
    assert "Kind of Blue" not in r2.text


def test_history_page_returns_200():
    r = _client().get("/history")
    assert r.status_code == 200
