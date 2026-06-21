import datetime
import random
from app.database import SessionLocal, init_db, engine, Base
from app.models import Album, QueueEntry, DailyPick
from app.queue_logic import initialize_queue
from app import daily


def setup_function():
    Base.metadata.drop_all(bind=engine)
    init_db()
    with SessionLocal() as s:
        for i in range(8):
            s.add(Album(title=f"A{i}", artist=f"Art{i}", year=1960 + i))
        s.commit()
        initialize_queue(s)


def _assert_invariants(s, seed_count):
    queue_count = s.query(QueueEntry).count()
    pending = {p.album_id for p in s.query(DailyPick).filter(DailyPick.status == "pending").all()}
    listened_ids = {p.album_id for p in s.query(DailyPick).filter(DailyPick.status == "listened").all()}
    queue_ids = {q.album_id for q in s.query(QueueEntry).all()}
    assert queue_ids.isdisjoint(listened_ids)
    assert len(queue_ids | listened_ids | pending) == seed_count
    positions = sorted(q.position for q in s.query(QueueEntry).all())
    assert positions == list(range(queue_count))
    assert len(queue_ids) == queue_count


def test_multi_day_cycle_conserves_albums_and_keeps_positions_contiguous():
    random.seed(123)
    with SessionLocal() as s:
        seed_count = s.query(Album).count()
        day = datetime.date(2026, 1, 1)
        for i in range(15):
            now = datetime.datetime.combine(day, datetime.time(9, 0))
            # 先解前一天的 gate（交替有聽/沒聽）
            gate = daily.pending_gate_pick(s, day)
            if gate is not None:
                daily.answer_gate(s, gate, listened=(i % 2 == 0))
            assert daily.pending_gate_pick(s, day) is None
            pick = daily.get_or_create_today_pick(s, day, now)
            assert pick is not None
            _assert_invariants(s, seed_count)
            day += datetime.timedelta(days=1)
