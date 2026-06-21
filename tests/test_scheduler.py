import datetime
from app.database import SessionLocal, init_db, engine, Base
from app.models import Album, DailyPick
from app.queue_logic import initialize_queue
from app import scheduler


def setup_function():
    Base.metadata.drop_all(bind=engine)
    init_db()
    with SessionLocal() as s:
        for i in range(3):
            s.add(Album(title=f"A{i}", artist=f"Art{i}", year=2000 + i))
        s.commit()
        initialize_queue(s)


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
