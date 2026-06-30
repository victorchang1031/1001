import datetime
from app.database import SessionLocal, init_db, engine, Base
from app.models import User, Album, DailyPick
from app import scheduler


def setup_function():
    Base.metadata.drop_all(bind=engine)
    init_db()
    with SessionLocal() as s:
        for i in range(3):
            s.add(Album(title=f"A{i}", artist=f"Art{i}", year=2000 + i))
        s.add(User(slug="u1"))
        s.commit()


def test_run_daily_job_creates_pick_when_revealed(monkeypatch):
    fixed = datetime.datetime(2026, 6, 21, 9, 0)

    class FakeDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    monkeypatch.setattr(scheduler.datetime, "datetime", FakeDateTime)
    scheduler.run_daily_job()
    with SessionLocal() as s:
        assert s.query(DailyPick).count() == 1


def test_daily_job_creates_personal_and_group_picks():
    import datetime
    from unittest.mock import patch
    from app.database import SessionLocal, init_db, engine, Base
    from app.models import User, Album, Server, Membership, DailyPick
    from app import scheduler
    Base.metadata.drop_all(bind=engine)
    init_db()
    with SessionLocal() as s:
        s.add(Album(title="A", artist="Art", year=2000))
        u = User(slug="u1"); srv = Server(slug="g1", name="g1")
        s.add_all([u, srv]); s.commit()
        s.add(Membership(user_id=u.id, server_id=srv.id)); s.commit()
    fixed = datetime.datetime(2026, 6, 21, 8, 30)

    class _DT(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    with patch.object(scheduler.datetime, "datetime", _DT):
        scheduler.run_daily_job()
    with SessionLocal() as s:
        picks = s.query(DailyPick).all()
        scopes = sorted([p.server_id for p in picks], key=lambda x: (x is not None, x))
        assert None in scopes          # 個人
        assert any(sid is not None for sid in scopes)  # 群組
