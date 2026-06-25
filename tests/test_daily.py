import datetime
from app.database import SessionLocal, init_db, engine, Base
from app.models import Album, DailyPick
from app.queue_logic import initialize_queue
from app import daily


def setup_function():
    Base.metadata.drop_all(bind=engine)
    init_db()
    with SessionLocal() as s:
        for i in range(5):
            s.add(Album(title=f"A{i}", artist=f"Art{i}", year=2000 + i))
        s.commit()
        initialize_queue(s)


def test_is_revealed():
    assert daily.is_revealed(datetime.datetime(2026, 6, 21, 8, 0)) is True
    assert daily.is_revealed(datetime.datetime(2026, 6, 21, 7, 59)) is False


def test_before_reveal_returns_none():
    with SessionLocal() as s:
        now = datetime.datetime(2026, 6, 21, 7, 0)
        assert daily.get_or_create_today_pick(s, now.date(), now) is None


def test_create_today_pick_and_wikipedia_link():
    with SessionLocal() as s:
        now = datetime.datetime(2026, 6, 21, 8, 30)
        pick = daily.get_or_create_today_pick(s, now.date(), now)
        assert pick is not None
        assert pick.status == "pending"
        daily.enrich_album(s, pick.album)
        assert pick.album.wikipedia_url.startswith("https://en.wikipedia.org/w/index.php?search=")


def test_gate_blocks_new_pick_until_answered():
    with SessionLocal() as s:
        day1 = datetime.datetime(2026, 6, 21, 8, 30)
        p1 = daily.get_or_create_today_pick(s, day1.date(), day1)
        day2 = datetime.datetime(2026, 6, 22, 8, 30)
        # 昨日 pending，今天應被擋
        assert daily.get_or_create_today_pick(s, day2.date(), day2) is None
        gate = daily.pending_gate_pick(s, day2.date())
        assert gate.id == p1.id
        daily.answer_gate(s, gate, listened=True)
        p2 = daily.get_or_create_today_pick(s, day2.date(), day2)
        assert p2 is not None
        assert p2.id != p1.id


def test_skip_reinserts_album():
    with SessionLocal() as s:
        from app.models import QueueEntry
        day1 = datetime.datetime(2026, 6, 21, 8, 30)
        p1 = daily.get_or_create_today_pick(s, day1.date(), day1)
        before = s.query(QueueEntry).count()
        daily.answer_gate(s, p1, listened=False)
        assert p1.status == "skipped"
        assert s.query(QueueEntry).count() == before + 1


def test_add_comment():
    with SessionLocal() as s:
        day1 = datetime.datetime(2026, 6, 21, 8, 30)
        p1 = daily.get_or_create_today_pick(s, day1.date(), day1)
        c = daily.add_comment(s, p1, "nice", 4)
        assert c.rating == 4
        assert p1.comments[0].content == "nice"
