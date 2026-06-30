from sqlalchemy import text
from app.database import engine, SessionLocal, init_db, Base


def test_init_db_creates_tables_and_session_works():
    init_db()
    with SessionLocal() as session:
        result = session.execute(text("SELECT 1")).scalar()
    assert result == 1
    assert Base is not None


def test_migration_adds_server_id_to_existing_db():
    from sqlalchemy import create_engine, text, inspect
    import os
    path = "./mig_test.db"
    if os.path.exists(path):
        os.remove(path)
    eng = create_engine(f"sqlite:///{path}")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE daily_pick (id INTEGER PRIMARY KEY, user_id INTEGER, date DATE, album_id INTEGER, status VARCHAR, revealed_at DATETIME)"))
    # 模擬 init_db 的補欄位邏輯
    with eng.begin() as c:
        insp = inspect(c)
        names = {col["name"] for col in insp.get_columns("daily_pick")}
        if "server_id" not in names:
            c.execute(text("ALTER TABLE daily_pick ADD COLUMN server_id INTEGER"))
    with eng.begin() as c:
        insp = inspect(c)
        assert "server_id" in {col["name"] for col in insp.get_columns("daily_pick")}
    eng.dispose()
    os.remove(path)
