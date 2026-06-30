import datetime
import threading
from sqlalchemy import func
from app.models import User, Album, DailyPick, Comment, Membership
from app.spotify import ensure_spotify_url
from app.music_links import wikipedia_url
from app.config import settings


def scope(col, server):
    return col == server.id if server else col.is_(None)


def enrich_album(db, album: Album) -> None:
    if not album.wikipedia_url:
        album.wikipedia_url = wikipedia_url(album.title, album.artist)
        db.commit()
    ensure_spotify_url(db, album)


def _enrich_album_async(album_id: int) -> None:
    # ponytail: 維基/Spotify 查詢搬到背景，免得 reveal 後第一個訪客卡在網路 I/O；
    # 首次渲染可能還沒連結/封面，重整後就補上
    def work():
        from app.database import SessionLocal
        with SessionLocal() as db:
            album = db.get(Album, album_id)
            if album is None:
                return
            try:
                enrich_album(db, album)
            except Exception:
                db.rollback()
    threading.Thread(target=work, daemon=True).start()


def is_revealed(now: datetime.datetime) -> bool:
    return now.hour >= settings.reveal_hour


def pending_gate_pick(db, user: User, today: datetime.date, server=None) -> DailyPick | None:
    return (
        db.query(DailyPick)
        .filter(
            DailyPick.user_id == user.id,
            scope(DailyPick.server_id, server),
            DailyPick.date < today,
            DailyPick.status == "pending",
        )
        .order_by(DailyPick.date)
        .first()
    )


def answer_gate(db, pick: DailyPick, listened: bool) -> None:
    pick.status = "listened" if listened else "skipped"
    db.commit()


def _pick_unseen_album(db, user: User, server=None) -> Album | None:
    # 群組情境下「聽過」算整組共同進度，不分誰聽的；個人情境維持只看自己
    listened = db.query(DailyPick.album_id).filter(DailyPick.status == "listened")
    if server:
        listened = listened.filter(DailyPick.server_id == server.id)
    else:
        listened = listened.filter(DailyPick.user_id == user.id, DailyPick.server_id.is_(None))
    return (
        db.query(Album)
        .filter(Album.id.notin_(listened))
        .order_by(func.random())
        .first()
    )


def _group_album_id_for_today(db, server, today: datetime.date) -> int | None:
    pick = (
        db.query(DailyPick)
        .filter(DailyPick.server_id == server.id, DailyPick.date == today)
        .first()
    )
    return pick.album_id if pick else None


def get_or_create_today_pick(db, user: User, today: datetime.date, now: datetime.datetime, server=None) -> DailyPick | None:
    if not is_revealed(now):
        return None
    existing = (
        db.query(DailyPick)
        .filter(DailyPick.user_id == user.id, scope(DailyPick.server_id, server), DailyPick.date == today)
        .first()
    )
    if existing:
        return existing
    if pending_gate_pick(db, user, today, server) is not None:
        return None
    # 群組已有人今天先抽過，就跟著用同一張；否則才重新抽（同組當天共用同張專輯）
    album = None
    if server:
        group_album_id = _group_album_id_for_today(db, server, today)
        if group_album_id is not None:
            album = db.get(Album, group_album_id)
    if album is None:
        album = _pick_unseen_album(db, user, server)
    if album is None:
        return None
    pick = DailyPick(
        user_id=user.id,
        server_id=server.id if server else None,
        date=today,
        album_id=album.id,
        status="pending",
        revealed_at=now,
    )
    db.add(pick)
    db.commit()
    _enrich_album_async(album.id)
    return pick


def server_members_today(db, server, today: datetime.date):
    out = []
    for m in db.query(Membership).filter_by(server_id=server.id).all():
        u = db.get(User, m.user_id)
        pick = (
            db.query(DailyPick)
            .filter_by(user_id=u.id, server_id=server.id, date=today)
            .first()
        )
        out.append((u, pick))
    return out


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
