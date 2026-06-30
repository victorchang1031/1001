from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config import settings


class Base(DeclarativeBase):
    pass


_url = settings.database_url
if _url.startswith("postgres://"):
    # Render 給的是 postgres://，SQLAlchemy 2.0 只認 postgresql://
    _url = _url.replace("postgres://", "postgresql://", 1)

_connect_args = {"check_same_thread": False} if _url.startswith("sqlite") else {}
engine = create_engine(_url, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    import app.models  # noqa: F401  確保 model 已註冊
    Base.metadata.create_all(bind=engine)
    from sqlalchemy import inspect, text
    with engine.begin() as conn:
        insp = inspect(conn)
        tables = set(insp.get_table_names())

        def cols(t):
            return {c["name"] for c in insp.get_columns(t)}

        # ponytail: create_all 不會替既有表補欄位，缺才 ALTER；型別 SQLite/PG 通用
        if "user" in tables and "name" not in cols("user"):
            conn.execute(text('ALTER TABLE "user" ADD COLUMN name VARCHAR'))
        if "daily_pick" in tables and "server_id" not in cols("daily_pick"):
            conn.execute(text("ALTER TABLE daily_pick ADD COLUMN server_id INTEGER"))
        if "draw_history" in tables and "server_id" not in cols("draw_history"):
            conn.execute(text("ALTER TABLE draw_history ADD COLUMN server_id INTEGER"))
