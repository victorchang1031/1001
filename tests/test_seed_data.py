from app.database import SessionLocal, init_db, engine, Base
from app.models import Album
from app.seed_data import seed_albums, SAMPLE_ALBUMS


def setup_function():
    Base.metadata.drop_all(bind=engine)
    init_db()


def test_seed_inserts_when_empty():
    with SessionLocal() as s:
        count = seed_albums(s)
        assert count == len(SAMPLE_ALBUMS)
        assert s.query(Album).count() == len(SAMPLE_ALBUMS)


def test_seed_idempotent():
    with SessionLocal() as s:
        seed_albums(s)
        assert seed_albums(s) == 0
        assert s.query(Album).count() == len(SAMPLE_ALBUMS)


def test_sample_has_required_fields():
    assert len(SAMPLE_ALBUMS) >= 12
    for a in SAMPLE_ALBUMS:
        assert a["title"] and a["artist"]
        assert isinstance(a["year"], int)
        assert "genre" in a
