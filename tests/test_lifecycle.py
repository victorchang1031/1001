import datetime
import random
from app.database import SessionLocal, init_db, engine, Base
from app.models import User, Album, DailyPick
from app import daily


def setup_function():
    Base.metadata.drop_all(bind=engine)
    init_db()
    with SessionLocal() as s:
        for i in range(8):
            s.add(Album(title=f"A{i}", artist=f"Art{i}", year=1960 + i))
        s.add(User(slug="u1"))
        s.commit()


def test_multi_day_cycle_never_repeats_listened_and_conserves_albums():
    random.seed(123)
    with SessionLocal() as s:
        user = s.query(User).first()
        total = s.query(Album).count()
        day = datetime.date(2026, 1, 1)
        for i in range(15):
            now = datetime.datetime.combine(day, datetime.time(9, 0))
            gate = daily.pending_gate_pick(s, user, day)
            if gate is not None:
                daily.answer_gate(s, gate, listened=(i % 2 == 0))
            assert daily.pending_gate_pick(s, user, day) is None
            pick = daily.get_or_create_today_pick(s, user, day, now)
            if pick is None:
                # 全部聽完就沒得抽了，合理
                break

            listened_ids = [
                p.album_id
                for p in s.query(DailyPick).filter(
                    DailyPick.user_id == user.id, DailyPick.status == "listened"
                )
            ]
            # 聽過的不再被抽到，每張聽過只一筆，且不超過總數
            assert pick.album_id not in listened_ids
            assert len(listened_ids) == len(set(listened_ids))
            assert len(set(listened_ids)) <= total
            day += datetime.timedelta(days=1)
