import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from app.database import SessionLocal
from app.daily import get_or_create_today_pick
from app.config import settings


def run_daily_job() -> None:
    now = datetime.datetime.now()
    with SessionLocal() as db:
        get_or_create_today_pick(db, now.date(), now)


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_daily_job, "cron", hour=settings.reveal_hour, minute=0)
    scheduler.start()
    return scheduler
