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


def test_draw_returns_album_and_records_history():
    from app.models import DrawHistory
    r = _client().get("/draw")
    assert r.status_code == 200
    with SessionLocal() as s:
        assert s.query(DrawHistory).count() == 1


def test_draw_history_page_lists_records():
    c = _client()
    c.get("/draw")
    r = c.get("/draw/history")
    assert r.status_code == 200
    assert "Kind of Blue" in r.text or "Thriller" in r.text


def test_albums_page_search():
    c = _client()
    r = c.get("/albums", params={"q": "Thriller"})
    assert "Thriller" in r.text
    assert "Kind of Blue" not in r.text


def test_album_detail_returns_200():
    with SessionLocal() as s:
        album = s.query(Album).filter_by(title="Kind of Blue").first()
        album_id = album.id
    r = _client().get(f"/albums/{album_id}")
    assert r.status_code == 200
    assert "Kind of Blue" in r.text


def test_album_detail_404_for_missing_album():
    r = _client().get("/albums/999999")
    assert r.status_code == 404


def test_stats_page_returns_200():
    r = _client().get("/stats")
    assert r.status_code == 200
    assert "專輯總數" in r.text
