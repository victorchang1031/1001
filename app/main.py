import datetime
from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import init_db, get_db, SessionLocal
from app.models import Album, DailyPick
from app.queue_logic import initialize_queue
from app.seed_data import seed_albums
from app.scheduler import start_scheduler
from app import daily

app = FastAPI()
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.on_event("startup")
def on_startup():
    init_db()
    with SessionLocal() as db:
        seed_albums(db)
        initialize_queue(db)
    start_scheduler()


@app.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    now = datetime.datetime.now()
    today = now.date()
    gate = daily.pending_gate_pick(db, today)
    pick = None
    if gate is None:
        pick = daily.get_or_create_today_pick(db, today, now)
    return templates.TemplateResponse(
        "index.html", {"request": request, "gate": gate, "pick": pick}
    )


@app.post("/gate")
def gate(pick_id: int = Form(...), listened: str = Form(...), db: Session = Depends(get_db)):
    pick = db.query(DailyPick).get(pick_id)
    if pick:
        daily.answer_gate(db, pick, listened == "yes")
    return RedirectResponse("/", status_code=303)


@app.post("/comment")
def comment(
    pick_id: int = Form(...),
    content: str = Form(...),
    rating: str = Form(""),
    db: Session = Depends(get_db),
):
    pick = db.query(DailyPick).get(pick_id)
    if pick:
        daily.add_comment(db, pick, content, int(rating) if rating else None)
    return RedirectResponse("/", status_code=303)


@app.get("/history")
def history(request: Request, db: Session = Depends(get_db)):
    picks = db.query(DailyPick).order_by(DailyPick.date.desc()).all()
    return templates.TemplateResponse(
        "history.html", {"request": request, "picks": picks}
    )


@app.get("/albums")
def albums(
    request: Request,
    decade: str = "",
    genre: str = "",
    status: str = "",
    letter: str = "",
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
        "albums.html",
        {
            "request": request,
            "albums": result,
            "decades": decades,
            "genres": genres,
            "letters": letters,
            "selected": {"decade": decade, "genre": genre, "status": status, "letter": letter},
        },
    )
