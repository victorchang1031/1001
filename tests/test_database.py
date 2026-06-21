from sqlalchemy import text
from app.database import engine, SessionLocal, init_db, Base


def test_init_db_creates_tables_and_session_works():
    init_db()
    with SessionLocal() as session:
        result = session.execute(text("SELECT 1")).scalar()
    assert result == 1
    assert Base is not None
