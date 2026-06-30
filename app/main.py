import datetime
import os
import secrets
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import init_db, get_db, SessionLocal
from app.models import User, Server, Membership, Album, DailyPick, DrawHistory, Comment
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
    start_scheduler()
    start_cover_backfill()
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["css_version"] = lambda: int(os.path.getmtime("app/static/style.css"))
templates.env.globals["wiki_search_url"] = wikipedia_search_url

COOKIE_MAX_AGE = 60 * 60 * 24 * 365 * 5


def set_gid_cookie(resp, slug: str):
    resp.set_cookie("gid", slug, max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax")


@app.middleware("http")
async def ensure_uid(request: Request, call_next):
    # 身分用 cookie slug 認；?u=<slug> 換裝置/分享。群組情境用 ?g=<slug> + cookie gid。
    incoming = request.query_params.get("u")
    slug = incoming or request.cookies.get("uid") or secrets.token_urlsafe(9)
    request.state.uid = slug
    incoming_g = request.query_params.get("g")
    request.state.gid = incoming_g if incoming_g is not None else (request.cookies.get("gid") or "")
    response = await call_next(request)
    if incoming or not request.cookies.get("uid"):
        response.set_cookie("uid", slug, max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax")
    if incoming_g is not None:
        if incoming_g:
            set_gid_cookie(response, incoming_g)
        else:
            response.delete_cookie("gid")
    return response


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = db.query(User).filter(User.slug == request.state.uid).first()
    if user is None:
        user = User(slug=request.state.uid)
        db.add(user)
        db.commit()
    return user


def get_current_server(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Server | None:
    gid = request.state.gid
    if not gid:
        return None
    server = db.query(Server).filter(Server.slug == gid).first()
    if server is None:
        return None
    is_member = (
        db.query(Membership).filter_by(user_id=user.id, server_id=server.id).first()
    )
    return server if is_member else None


@app.get("/")
def home(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    server: Server | None = Depends(get_current_server),
):
    now = datetime.datetime.now()
    today = now.date()
    gate = daily.pending_gate_pick(db, user, today, server=server)
    pick = None
    if gate is None:
        pick = daily.get_or_create_today_pick(db, user, today, now, server=server)
    members = daily.server_members_today(db, server, today) if server else None
    return templates.TemplateResponse(
        request, "index.html", {"gate": gate, "pick": pick, "server": server, "members": members}
    )


@app.post("/gate")
def gate(
    pick_id: int = Form(...),
    listened: str = Form(...),
    content: str = Form(""),
    rating: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    pick = db.get(DailyPick, pick_id)
    if pick and pick.user_id == user.id:
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
    user: User = Depends(get_current_user),
):
    pick = db.get(DailyPick, pick_id)
    if pick and pick.user_id == user.id:
        daily.add_comment(db, pick, content, int(rating) if rating else None)
    return RedirectResponse("/", status_code=303)


@app.get("/admin/spotify-status")
def spotify_status(key: str = ""):
    if not settings.admin_key or key != settings.admin_key:
        raise HTTPException(status_code=403, detail="forbidden")
    import httpx
    from app import spotify
    spotify._token_cache.update(token=None, expires_at=0.0)
    creds = bool(settings.spotify_client_id and settings.spotify_client_secret)
    token_ok = False
    probe = None
    if creds:
        with httpx.Client() as c:
            token = spotify.get_access_token(c)
            token_ok = bool(token)
            if token:
                r = c.get(spotify.SEARCH_URL,
                          headers={"Authorization": f"Bearer {token}"},
                          params={"q": "Thriller artist:Michael Jackson", "type": "album", "limit": 5})
                items = r.json().get("albums", {}).get("items", []) if r.status_code == 200 else []
                probe = {"status": r.status_code, "items": len(items),
                         "retry_after": r.headers.get("retry-after")}
    rid = os.getenv("SPOTIFY_CLIENT_ID")
    rsecret = os.getenv("SPOTIFY_CLIENT_SECRET")
    return {
        "creds_present": creds,
        "token_ok": token_ok,
        "search_probe": probe,
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
def history(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user), server: Server | None = Depends(get_current_server)):
    picks = (
        db.query(DailyPick)
        .filter(DailyPick.user_id == user.id, daily.scope(DailyPick.server_id, server))
        .order_by(DailyPick.date.desc())
        .all()
    )
    return templates.TemplateResponse(
        request, "history.html", {"picks": picks}
    )


@app.get("/draw")
def draw(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user), server: Server | None = Depends(get_current_server)):
    album = db.query(Album).order_by(func.random()).first()
    ensure_spotify_url(db, album)
    if not album.wikipedia_url:
        album.wikipedia_url = wikipedia_url(album.title, album.artist)
    db.add(DrawHistory(user_id=user.id, server_id=server.id if server else None, album_id=album.id, drawn_at=datetime.datetime.now()))
    db.commit()
    keep_ids = (
        db.query(DrawHistory.id)
        .filter(DrawHistory.user_id == user.id, daily.scope(DrawHistory.server_id, server))
        .order_by(DrawHistory.drawn_at.desc(), DrawHistory.id.desc())
        .limit(25)
    )
    db.query(DrawHistory).filter(
        DrawHistory.user_id == user.id, daily.scope(DrawHistory.server_id, server), DrawHistory.id.notin_(keep_ids)
    ).delete(synchronize_session=False)
    db.commit()
    return templates.TemplateResponse(request, "draw.html", {"album": album})


@app.get("/draw/history")
def draw_history(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user), server: Server | None = Depends(get_current_server)):
    records = (
        db.query(DrawHistory)
        .filter(DrawHistory.user_id == user.id, daily.scope(DrawHistory.server_id, server))
        .order_by(DrawHistory.drawn_at.desc())
        .all()
    )
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
    user: User = Depends(get_current_user),
    server: Server | None = Depends(get_current_server),
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
        picks = db.query(DailyPick).filter(DailyPick.user_id == user.id, daily.scope(DailyPick.server_id, server)).all()
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
def album_detail(request: Request, album_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user), server: Server | None = Depends(get_current_server)):
    album = db.get(Album, album_id)
    if album is None:
        raise HTTPException(status_code=404, detail="Album not found")
    picks = (
        db.query(DailyPick)
        .filter(DailyPick.album_id == album_id, DailyPick.user_id == user.id, daily.scope(DailyPick.server_id, server))
        .order_by(DailyPick.date.desc())
        .all()
    )
    return templates.TemplateResponse(
        request, "album_detail.html", {"album": album, "picks": picks}
    )


@app.get("/groups")
def groups(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        db.query(Server)
        .join(Membership, Membership.server_id == Server.id)
        .filter(Membership.user_id == user.id)
        .order_by(Server.created_at)
        .all()
    )
    return templates.TemplateResponse(request, "groups.html", {"servers": rows, "me": user})


@app.post("/groups")
def create_group(name: str = Form(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    server = Server(slug=secrets.token_urlsafe(6), name=name)
    db.add(server)
    db.commit()
    db.add(Membership(user_id=user.id, server_id=server.id))
    db.commit()
    resp = RedirectResponse("/", status_code=303)
    set_gid_cookie(resp, server.slug)
    return resp


@app.post("/me")
def set_name(name: str = Form(""), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    user.name = name or None
    db.commit()
    return RedirectResponse("/groups", status_code=303)


@app.get("/s/{slug}")
def server_entry(slug: str, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    server = db.query(Server).filter(Server.slug == slug).first()
    if server is None:
        raise HTTPException(status_code=404, detail="group not found")
    member = db.query(Membership).filter_by(user_id=user.id, server_id=server.id).first()
    if member:
        resp = RedirectResponse("/", status_code=303)
        set_gid_cookie(resp, server.slug)
        return resp
    return templates.TemplateResponse(request, "join.html", {"server": server})


@app.post("/s/{slug}/join")
def join_server(slug: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    server = db.query(Server).filter(Server.slug == slug).first()
    if server is None:
        raise HTTPException(status_code=404, detail="group not found")
    if not db.query(Membership).filter_by(user_id=user.id, server_id=server.id).first():
        db.add(Membership(user_id=user.id, server_id=server.id))
        db.commit()
    resp = RedirectResponse("/", status_code=303)
    set_gid_cookie(resp, server.slug)
    return resp


@app.get("/stats")
def stats(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user), server: Server | None = Depends(get_current_server)):
    sc = daily.scope(DailyPick.server_id, server)
    mine = db.query(DailyPick).filter(DailyPick.user_id == user.id, sc)
    total_albums = db.query(Album).count()
    listened = mine.filter(DailyPick.status == "listened").count()
    skipped = mine.filter(DailyPick.status == "skipped").count()
    seen_album_ids = {
        row[0]
        for row in db.query(DailyPick.album_id).filter(DailyPick.user_id == user.id, sc).distinct()
    }
    unseen = total_albums - len(seen_album_ids)
    avg_rating = (
        db.query(func.avg(Comment.rating))
        .join(DailyPick, Comment.daily_pick_id == DailyPick.id)
        .filter(DailyPick.user_id == user.id, sc, Comment.rating.isnot(None))
        .scalar()
    )
    top_albums = (
        db.query(Album, func.avg(Comment.rating).label("avg_rating"))
        .join(DailyPick, DailyPick.album_id == Album.id)
        .join(Comment, Comment.daily_pick_id == DailyPick.id)
        .filter(DailyPick.user_id == user.id, sc, Comment.rating.isnot(None))
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
