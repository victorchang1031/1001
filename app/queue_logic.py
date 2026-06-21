import random
from app.models import Album, QueueEntry
from app.config import settings


def initialize_queue(db) -> None:
    if db.query(QueueEntry).count() > 0:
        return
    album_ids = [a.id for a in db.query(Album).order_by(Album.id).all()]
    rng = random.Random(settings.random_seed)
    rng.shuffle(album_ids)
    for pos, album_id in enumerate(album_ids):
        db.add(QueueEntry(album_id=album_id, position=pos))
    db.commit()


def peek_next(db) -> Album | None:
    entry = db.query(QueueEntry).order_by(QueueEntry.position).first()
    return entry.album if entry else None


def _compact(db) -> None:
    for pos, e in enumerate(db.query(QueueEntry).order_by(QueueEntry.position).all()):
        e.position = pos
    db.commit()


def pop_next(db) -> Album | None:
    entry = db.query(QueueEntry).order_by(QueueEntry.position).first()
    if entry is None:
        return None
    album = entry.album
    db.delete(entry)
    db.commit()
    _compact(db)
    return album


def reinsert_random(db, album_id: int) -> None:
    entries = db.query(QueueEntry).order_by(QueueEntry.position).all()
    n = len(entries)
    insert_at = random.randint(0, max(0, n - 1))
    for e in entries:
        if e.position >= insert_at:
            e.position += 1
    db.add(QueueEntry(album_id=album_id, position=insert_at))
    db.commit()
    _compact(db)
