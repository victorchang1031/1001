import datetime
from app.database import SessionLocal, init_db, engine, Base
from app.models import Album, QueueEntry, DailyPick, Comment


def setup_function():
    Base.metadata.drop_all(bind=engine)
    init_db()


def test_create_album_and_relationships():
    with SessionLocal() as s:
        album = Album(title="Kind of Blue", artist="Miles Davis", year=1959, genre="Jazz")
        s.add(album)
        s.flush()
        s.add(QueueEntry(album_id=album.id, position=0))
        pick = DailyPick(
            date=datetime.date(2026, 6, 21),
            album_id=album.id,
            status="pending",
            revealed_at=datetime.datetime(2026, 6, 21, 8, 0),
        )
        s.add(pick)
        s.flush()
        s.add(Comment(daily_pick_id=pick.id, content="great", rating=5,
                      created_at=datetime.datetime.now()))
        s.commit()

        loaded = s.query(DailyPick).first()
        assert loaded.album.title == "Kind of Blue"
        assert loaded.comments[0].rating == 5
        assert loaded.status == "pending"
