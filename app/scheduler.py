import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from app.database import SessionLocal
from app.models import User, Server, Membership
from app.daily import get_or_create_today_pick
from app.config import settings


def run_daily_job() -> None:
    now = datetime.datetime.now()
    today = now.date()
    with SessionLocal() as db:
        for user in db.query(User).all():
            get_or_create_today_pick(db, user, today, now)
        for m in db.query(Membership).all():
            user = db.get(User, m.user_id)
            server = db.get(Server, m.server_id)
            get_or_create_today_pick(db, user, today, now, server=server)


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_daily_job, "cron", hour=settings.reveal_hour, minute=0)
    scheduler.start()
    return scheduler
