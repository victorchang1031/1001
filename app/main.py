import datetime
import os
import random
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import init_db, get_db, SessionLocal
from app.models import Album, DailyPick, DrawHistory, Comment
from app.queue_logic import initialize_queue
from app.seed_data import seed_albums, dedup_albums
from app.scheduler import start_scheduler
from app.config import settings
from app.spotify import ensure_spotify_url, start_cover_backfill
from app.music_links import wikipedia_url, wikipedia_search_url
from app import daily


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as db:
        seed_albums(db)
        dedup_albums(db)
        initialize_queue(db)
    start_scheduler()
    start_cover_backfill()
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["css_version"] = lambda: int(os.path.getmtime("app/static/style.css"))
templates.env.globals["wiki_search_url"] = wikipedia_search_url


@app.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    now = datetime.datetime.now()
    today = now.date()
    gate = daily.pending_gate_pick(db, today)
    pick = None
    if gate is None:
        pick = daily.get_or_create_today_pick(db, today, now)
    return templates.TemplateResponse(
        request, "index.html", {"gate": gate, "pick": pick}
    )


@app.post("/gate")
def gate(
    pick_id: int = Form(...),
    listened: str = Form(...),
    content: str = Form(""),
    rating: str = Form(""),
    db: Session = Depends(get_db),
):
    pick = db.get(DailyPick, pick_id)
    if pick:
        daily.answer_gate(db, pick, listened == "yes")
        if listened == "yes" and content:
            daily.add_comment(db, pick, content, int(rating) if rating else None)
    return RedirectResponse("/", status_code=303)


@app.post("/comment")
def comment(
    pick_id: int = Form(...),
    content: str = Form(...),
    rating: str = Form(""),
    db: Session = Depends(get_db),
):
    pick = db.get(DailyPick, pick_id)
    if pick:
        daily.add_comment(db, pick, content, int(rating) if rating else None)
    return RedirectResponse("/", status_code=303)


@app.get("/admin/spotify-status")
def spotify_status():
    import httpx
    from app import spotify
    spotify._token_cache.update(token=None, expires_at=0.0)
    creds = bool(settings.spotify_client_id and settings.spotify_client_secret)
    token_ok = False
    if creds:
        with httpx.Client() as c:
            token_ok = bool(spotify.get_access_token(c))
    rid = os.getenv("SPOTIFY_CLIENT_ID")
    rsecret = os.getenv("SPOTIFY_CLIENT_SECRET")
    return {
        "creds_present": creds,
        "token_ok": token_ok,
        "env_keys_seen": [k for k in os.environ if "SPOTIFY" in k.upper()],
        "id_len": len(rid) if rid else 0,
        "secret_len": len(rsecret) if rsecret else 0,
        "id_has_whitespace": bool(rid and rid != rid.strip()),
        "secret_has_whitespace": bool(rsecret and rsecret != rsecret.strip()),
    }


@app.get("/admin/refetch-covers")
def refetch_covers(key: str, db: Session = Depends(get_db)):
    if not settings.admin_key or key != settings.admin_key:
        raise HTTPException(status_code=403, detail="forbidden")
    start_cover_backfill(force=True)
    return {"status": "refetching all covers in background", "albums": db.query(Album).count()}


@app.get("/history")
def history(request: Request, db: Session = Depends(get_db)):
    picks = db.query(DailyPick).order_by(DailyPick.date.desc()).all()
    return templates.TemplateResponse(
        request, "history.html", {"picks": picks}
    )


@app.get("/draw")
def draw(request: Request, db: Session = Depends(get_db)):
    album = random.choice(db.query(Album).all())
    ensure_spotify_url(db, album)
    if not album.wikipedia_url:
        album.wikipedia_url = wikipedia_url(album.title, album.artist)
    db.add(DrawHistory(album_id=album.id, drawn_at=datetime.datetime.now()))
    db.commit()
    keep_ids = db.query(DrawHistory.id).order_by(DrawHistory.drawn_at.desc(), DrawHistory.id.desc()).limit(25)
    db.query(DrawHistory).filter(DrawHistory.id.notin_(keep_ids)).delete(synchronize_session=False)
    db.commit()
    return templates.TemplateResponse(request, "draw.html", {"album": album})


@app.get("/draw/history")
def draw_history(request: Request, db: Session = Depends(get_db)):
    records = db.query(DrawHistory).order_by(DrawHistory.drawn_at.desc()).all()
    return templates.TemplateResponse(request, "draw_history.html", {"records": records})


@app.get("/albums")
def albums(
    request: Request,
    decade: str = "",
    genre: str = "",
    status: str = "",
    letter: str = "",
    q: str = "",
    db: Session = Depends(get_db),
):
    query = db.query(Album)
    if decade:
        start = int(decade)
        query = query.filter(Album.year >= start, Album.year < start + 10)
    if genre:
        query = query.filter(Album.genre == genre)
    if letter:
        query = query.filter(Album.artist.ilike(f"{letter}%"))
    if q:
        query = query.filter(
            Album.title.ilike(f"%{q}%") | Album.artist.ilike(f"%{q}%")
        )
    result = query.order_by(Album.artist).all()

    if status:
        picks = db.query(DailyPick).all()
        listened_ids = {p.album_id for p in picks if p.status == "listened"}
        skipped_ids = {p.album_id for p in picks if p.status == "skipped"}
        seen_ids = {p.album_id for p in picks}
        if status == "listened":
            result = [a for a in result if a.id in listened_ids]
        elif status == "skipped":
            result = [a for a in result if a.id in skipped_ids]
        elif status == "unseen":
            result = [a for a in result if a.id not in seen_ids]

    all_albums = db.query(Album).all()
    decades = sorted({(a.year // 10) * 10 for a in all_albums})
    genres = sorted({a.genre for a in all_albums if a.genre})
    letters = sorted({a.artist[0].upper() for a in all_albums if a.artist})
    return templates.TemplateResponse(
        request,
        "albums.html",
        {
            "albums": result,
            "decades": decades,
            "genres": genres,
            "letters": letters,
            "selected": {"decade": decade, "genre": genre, "status": status, "letter": letter, "q": q},
        },
    )


@app.get("/albums/{album_id}")
def album_detail(request: Request, album_id: int, db: Session = Depends(get_db)):
    album = db.get(Album, album_id)
    if album is None:
        raise HTTPException(status_code=404, detail="Album not found")
    picks = (
        db.query(DailyPick)
        .filter(DailyPick.album_id == album_id)
        .order_by(DailyPick.date.desc())
        .all()
    )
    return templates.TemplateResponse(
        request, "album_detail.html", {"album": album, "picks": picks}
    )


@app.get("/stats")
def stats(request: Request, db: Session = Depends(get_db)):
    total_albums = db.query(Album).count()
    listened = db.query(DailyPick).filter(DailyPick.status == "listened").count()
    skipped = db.query(DailyPick).filter(DailyPick.status == "skipped").count()
    seen_album_ids = {row[0] for row in db.query(DailyPick.album_id).distinct()}
    unseen = total_albums - len(seen_album_ids)
    avg_rating = db.query(func.avg(Comment.rating)).filter(Comment.rating.isnot(None)).scalar()
    top_albums = (
        db.query(Album, func.avg(Comment.rating).label("avg_rating"))
        .join(DailyPick, DailyPick.album_id == Album.id)
        .join(Comment, Comment.daily_pick_id == DailyPick.id)
        .filter(Comment.rating.isnot(None))
        .group_by(Album.id)
        .order_by(func.avg(Comment.rating).desc())
        .limit(5)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "stats.html",
        {
            "total_albums": total_albums,
            "listened": listened,
            "skipped": skipped,
            "unseen": unseen,
            "avg_rating": avg_rating,
            "top_albums": top_albums,
        },
    )
