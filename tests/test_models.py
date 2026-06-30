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


def test_server_and_membership_and_scoped_columns():
    from app.database import SessionLocal, init_db, engine, Base
    from app.models import User, Server, Membership, DailyPick
    Base.metadata.drop_all(bind=engine)
    init_db()
    with SessionLocal() as s:
        u = User(slug="u1", name="Vic")
        srv = Server(slug="g1", name="Group One")
        s.add_all([u, srv]); s.commit()
        s.add(Membership(user_id=u.id, server_id=srv.id)); s.commit()
        import datetime
        p = DailyPick(user_id=u.id, server_id=srv.id, date=datetime.date(2026, 6, 30),
                      album_id=1, status="pending", revealed_at=datetime.datetime.now())
        s.add(p); s.commit()
        assert p.server_id == srv.id
        assert u.name == "Vic"
        # 個人情境：server_id 可為 None
        p2 = DailyPick(user_id=u.id, server_id=None, date=datetime.date(2026, 6, 29),
                       album_id=1, status="pending", revealed_at=datetime.datetime.now())
        s.add(p2); s.commit()
        assert p2.server_id is None
