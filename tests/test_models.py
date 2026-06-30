import datetime
from app.database import SessionLocal, init_db, engine, Base
from app.models import User, Album, DailyPick, Comment


def setup_function():
    Base.metadata.drop_all(bind=engine)
    init_db()


def test_create_album_and_relationships():
    with SessionLocal() as s:
        album = Album(title="Kind of Blue", artist="Miles Davis", year=1959, genre="Jazz")
        user = User(slug="u1")
        s.add_all([album, user])
        s.flush()
        pick = DailyPick(
            user_id=user.id,
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
