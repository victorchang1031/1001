import random
from app.database import SessionLocal, init_db, engine, Base
from app.models import Album, QueueEntry
from app.queue_logic import initialize_queue, peek_next, pop_next, reinsert_random


def setup_function():
    Base.metadata.drop_all(bind=engine)
    init_db()
    with SessionLocal() as s:
        for i in range(5):
            s.add(Album(title=f"A{i}", artist=f"Art{i}", year=2000 + i))
        s.commit()


def test_initialize_is_deterministic():
    with SessionLocal() as s:
        initialize_queue(s)
        order1 = [q.album_id for q in s.query(QueueEntry).order_by(QueueEntry.position)]
    Base.metadata.drop_all(bind=engine)
    init_db()
    with SessionLocal() as s:
        for i in range(5):
            s.add(Album(title=f"A{i}", artist=f"Art{i}", year=2000 + i))
        s.commit()
        initialize_queue(s)
        order2 = [q.album_id for q in s.query(QueueEntry).order_by(QueueEntry.position)]
    assert order1 == order2


def test_initialize_idempotent():
    with SessionLocal() as s:
        initialize_queue(s)
        initialize_queue(s)
        assert s.query(QueueEntry).count() == 5


def test_pop_removes_smallest_position():
    with SessionLocal() as s:
        initialize_queue(s)
        first = peek_next(s)
        popped = pop_next(s)
        assert popped.id == first.id
        assert s.query(QueueEntry).count() == 4


def test_reinsert_random_adds_back_in_range():
    with SessionLocal() as s:
        initialize_queue(s)
        popped = pop_next(s)  # 剩 4 筆
        random.seed(1)
        reinsert_random(s, popped.id)
        assert s.query(QueueEntry).count() == 5
        positions = [q.position for q in s.query(QueueEntry).order_by(QueueEntry.position)]
        assert positions == [0, 1, 2, 3, 4]  # 連續無洞
        ids = [q.album_id for q in s.query(QueueEntry).order_by(QueueEntry.position)]
        assert popped.id in ids
        assert ids[-1] != popped.id  # 不在最末尾（隨機插中間範圍）
