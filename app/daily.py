import datetime
from app.models import DailyPick, Comment
from app.queue_logic import pop_next, reinsert_random
from app.spotify import ensure_spotify_url
from app.music_links import wikipedia_url
from app.config import settings


def is_revealed(now: datetime.datetime) -> bool:
    return now.hour >= settings.reveal_hour


def pending_gate_pick(db, today: datetime.date) -> DailyPick | None:
    return (
        db.query(DailyPick)
        .filter(DailyPick.date < today, DailyPick.status == "pending")
        .order_by(DailyPick.date)
        .first()
    )


def answer_gate(db, pick: DailyPick, listened: bool) -> None:
    if listened:
        pick.status = "listened"
    else:
        pick.status = "skipped"
        reinsert_random(db, pick.album_id)
    db.commit()


def get_or_create_today_pick(db, today: datetime.date, now: datetime.datetime) -> DailyPick | None:
    if not is_revealed(now):
        return None
    existing = db.query(DailyPick).filter(DailyPick.date == today).first()
    if existing:
        return existing
    if pending_gate_pick(db, today) is not None:
        return None
    album = pop_next(db)
    if album is None:
        return None
    if not album.wikipedia_url:
        album.wikipedia_url = wikipedia_url(album.title, album.artist)
    ensure_spotify_url(db, album)
    pick = DailyPick(date=today, album_id=album.id, status="pending", revealed_at=now)
    db.add(pick)
    db.commit()
    return pick


def add_comment(db, pick: DailyPick, content: str, rating: int | None) -> Comment:
    comment = Comment(
        daily_pick_id=pick.id,
        content=content,
        rating=rating,
        created_at=datetime.datetime.now(),
    )
    db.add(comment)
    db.commit()
    return comment
