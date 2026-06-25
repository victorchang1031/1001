import datetime
from app.database import SessionLocal, init_db, engine, Base
from app.models import Album, QueueEntry, DailyPick, DrawHistory
from app.seed_data import seed_albums, dedup_albums, SAMPLE_ALBUMS


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


def test_dedup_keeps_one_and_reassigns_history():
    with SessionLocal() as s:
        keep = Album(title="Odessey & Oracle", artist="The Zombies", year=1968)
        drop = Album(title="Odessey And Oracle", artist="The Zombies", year=1968)
        other = Album(title="Revolver", artist="The Beatles", year=1966)
        s.add_all([keep, drop, other])
        s.commit()
        s.add(QueueEntry(album_id=drop.id, position=0))
        s.add(DrawHistory(album_id=drop.id, drawn_at=datetime.datetime.now()))
        s.add(DailyPick(date=datetime.date(2026, 1, 1), album_id=drop.id, revealed_at=datetime.datetime.now()))
        s.commit()
        keep_id, drop_id = keep.id, drop.id

        assert dedup_albums(s) == 1
        assert dedup_albums(s) == 0  # idempotent

        assert s.query(Album).count() == 2
        assert s.get(Album, drop_id) is None
        assert s.query(DrawHistory).filter_by(album_id=keep_id).count() == 1
        assert s.query(DailyPick).filter_by(album_id=keep_id).count() == 1
        assert s.query(QueueEntry).filter_by(album_id=drop_id).count() == 0


def test_sample_has_required_fields():
    assert len(SAMPLE_ALBUMS) >= 12
    for a in SAMPLE_ALBUMS:
        assert a["title"] and a["artist"]
        assert isinstance(a["year"], int)
