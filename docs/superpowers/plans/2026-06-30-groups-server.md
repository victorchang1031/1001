# 群組（伺服器）功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在既有單機多人專輯 App 上加「群組（伺服器）」層 —— 一帳號可建立/加入多個群組，群組內每人各自抽每日專輯但能互看，個人頁與群組頁並存。

**Architecture:** 沿用既有 cookie slug 身分（不加密碼）。新增 `Server` / `Membership`，並在 `DailyPick` / `DrawHistory` 加可空 `server_id`（NULL = 個人頁）。情境用既有 `?u=` 思路加一個 `?g=<slug>` + cookie `gid` 黏著，故導覽列連結不需改動。`server` 參數以「有預設值 None」加在函式簽名尾端，個人情境自動是 None，既有呼叫與測試大多不動。

**Tech Stack:** FastAPI、SQLAlchemy 2.0（SQLite 本機 / Postgres on Render）、Jinja2、APScheduler、pytest。

## Global Constraints

- 不加密碼 / OAuth 登入；身分維持 cookie slug。
- 不丟既有資料：既有 `daily_pick` / `draw_history` 加欄位後 `server_id` 為 NULL → 自動歸個人頁。
- 遷移須同時適用 SQLite 與 Postgres（欄位型別用 `VARCHAR` / `INTEGER`，`user` 表名加雙引號）。
- `server` 參數一律為「可空、預設 None」；個人情境 = None。
- 不做角色/權限/邀請過期/踢人。
- Cookie 設定統一：`max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax"`。
- 測試起點：`Base.metadata.drop_all(bind=engine); init_db()`（見 tests/conftest.py 用 `sqlite:///./test.db`）。

---

### Task 1: 資料模型與遷移

**Files:**
- Modify: `app/models.py`
- Modify: `app/database.py:28-30`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `Server(id, slug, name, created_at)`、`Membership(id, user_id, server_id, joined_at)`、`User.name: str | None`、`DailyPick.server_id: int | None`、`DrawHistory.server_id: int | None`。
- Produces: `init_db()` 會對既有表缺欄位時 `ALTER TABLE` 補上。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_models.py` 末尾加：

```python
def test_server_and_membership_and_scoped_columns():
    from app.database import SessionLocal, init_db, engine, Base
    from app.models import User, Server, Membership, DailyPick
    Base.metadata.drop_all(bind=engine)
    init_db()
    with SessionLocal() as s:
        u = User(slug="u1", name="Vic")
        srv = Server(slug="g1", name="Group One")
        s.add_all([u, srv]); s.commit()
        s.add(Membership(user_id=u.id, server_id=srv.id)); s.commit()
        import datetime
        p = DailyPick(user_id=u.id, server_id=srv.id, date=datetime.date(2026, 6, 30),
                      album_id=1, status="pending", revealed_at=datetime.datetime.now())
        s.add(p); s.commit()
        assert p.server_id == srv.id
        assert u.name == "Vic"
        # 個人情境：server_id 可為 None
        p2 = DailyPick(user_id=u.id, server_id=None, date=datetime.date(2026, 6, 29),
                       album_id=1, status="pending", revealed_at=datetime.datetime.now())
        s.add(p2); s.commit()
        assert p2.server_id is None
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_models.py::test_server_and_membership_and_scoped_columns -q`
Expected: FAIL（`ImportError: cannot import name 'Server'` 或欄位不存在）

- [ ] **Step 3: 改 models.py**

`User` 加 `name`；移除 `DailyPick` 的 `UniqueConstraint("user_id", "date")`；`DailyPick` / `DrawHistory` 加 `server_id`；新增 `Server` / `Membership`。

```python
class User(Base):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )


class Server(Base):
    __tablename__ = "server"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )


class Membership(Base):
    __tablename__ = "membership"
    __table_args__ = (UniqueConstraint("user_id", "server_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    server_id: Mapped[int] = mapped_column(ForeignKey("server.id"))
    joined_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )
```

`DailyPick`：拿掉 `__table_args__` 那行，並加 `server_id`：

```python
class DailyPick(Base):
    __tablename__ = "daily_pick"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    server_id: Mapped[int | None] = mapped_column(ForeignKey("server.id"), nullable=True)
    date: Mapped[datetime.date] = mapped_column(Date)
    album_id: Mapped[int] = mapped_column(ForeignKey("album.id"))
    status: Mapped[str] = mapped_column(String, default="pending")
    revealed_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    album: Mapped["Album"] = relationship()
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="daily_pick", cascade="all, delete-orphan"
    )
```

`DrawHistory` 加 `server_id`：

```python
class DrawHistory(Base):
    __tablename__ = "draw_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    server_id: Mapped[int | None] = mapped_column(ForeignKey("server.id"), nullable=True)
    album_id: Mapped[int] = mapped_column(ForeignKey("album.id"))
    drawn_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    album: Mapped["Album"] = relationship()
```

- [ ] **Step 4: 改 database.py 加遷移**

把 `init_db` 換成：

```python
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
```

- [ ] **Step 5: 跑測試確認通過**

Run: `python -m pytest tests/test_models.py -q`
Expected: PASS

- [ ] **Step 6: 遷移煙霧測試（既有 DB 補欄位）**

在 `tests/test_database.py` 末尾加：

```python
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
```

- [ ] **Step 7: 跑測試**

Run: `python -m pytest tests/test_database.py -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add app/models.py app/database.py tests/test_models.py tests/test_database.py
git commit -m "feat: add Server/Membership models, server_id scoping columns, column migration"
```

---

### Task 2: daily.py 加入 server 範圍

**Files:**
- Modify: `app/daily.py`
- Test: `tests/test_daily.py`

**Interfaces:**
- Consumes: Task 1 的 `Server`、`Membership`、`DailyPick.server_id`。
- Produces:
  - `scope(col, server) -> ColumnElement`：`col == server.id` 若 server，否則 `col.is_(None)`。
  - `pending_gate_pick(db, user, today, server=None)`
  - `get_or_create_today_pick(db, user, today, now, server=None)`（新 pick 設 `server_id = server.id if server else None`）
  - `_pick_unseen_album(db, user, server=None)`
  - `server_members_today(db, server, today) -> list[tuple[User, DailyPick | None]]`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_daily.py` 末尾加（沿用檔頭既有 `setup_function` 與 `_user`）：

```python
from app.models import Server, Membership


def _server(s, slug="g1"):
    srv = Server(slug=slug, name=slug)
    s.add(srv); s.commit()
    return srv


def test_personal_and_group_picks_are_independent():
    with SessionLocal() as s:
        u = _user(s)
        srv = _server(s)
        now = datetime.datetime(2026, 6, 21, 8, 30)
        personal = daily.get_or_create_today_pick(s, u, now.date(), now)
        group = daily.get_or_create_today_pick(s, u, now.date(), now, server=srv)
        assert personal is not None and group is not None
        assert personal.id != group.id
        assert personal.server_id is None
        assert group.server_id == srv.id


def test_group_gate_independent_from_personal():
    with SessionLocal() as s:
        u = _user(s)
        srv = _server(s)
        day1 = datetime.datetime(2026, 6, 21, 8, 30)
        daily.get_or_create_today_pick(s, u, day1.date(), day1, server=srv)
        day2 = datetime.datetime(2026, 6, 22, 8, 30)
        # 群組有未結清 gate，但個人情境不受影響
        assert daily.pending_gate_pick(s, u, day2.date(), server=srv) is not None
        assert daily.pending_gate_pick(s, u, day2.date()) is None
        assert daily.get_or_create_today_pick(s, u, day2.date(), day2) is not None


def test_server_members_today_lists_each_member_pick():
    with SessionLocal() as s:
        u1 = _user(s, "a"); u2 = _user(s, "b")
        srv = _server(s)
        s.add_all([Membership(user_id=u1.id, server_id=srv.id),
                   Membership(user_id=u2.id, server_id=srv.id)])
        s.commit()
        now = datetime.datetime(2026, 6, 21, 8, 30)
        daily.get_or_create_today_pick(s, u1, now.date(), now, server=srv)
        rows = daily.server_members_today(s, srv, now.date())
        by_slug = {u.slug: pick for u, pick in rows}
        assert set(by_slug) == {"a", "b"}
        assert by_slug["a"] is not None
        assert by_slug["b"] is None
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_daily.py -q`
Expected: FAIL（`get_or_create_today_pick() got unexpected keyword 'server'` 等）

- [ ] **Step 3: 改 daily.py**

加 `scope` 與 `server_members_today`，並把 `server` 串進三個函式。匯入加 `Membership`、`Server`：

```python
from app.models import User, Album, DailyPick, Comment, Membership


def scope(col, server):
    return col == server.id if server else col.is_(None)


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


def _pick_unseen_album(db, user: User, server=None) -> Album | None:
    listened = (
        db.query(DailyPick.album_id)
        .filter(
            DailyPick.user_id == user.id,
            scope(DailyPick.server_id, server),
            DailyPick.status == "listened",
        )
    )
    return (
        db.query(Album)
        .filter(Album.id.notin_(listened))
        .order_by(func.random())
        .first()
    )


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
```

- [ ] **Step 4: 跑測試確認通過（含既有測試未回歸）**

Run: `python -m pytest tests/test_daily.py -q`
Expected: PASS（既有個人情境測試仍過，因 `server` 預設 None）

- [ ] **Step 5: Commit**

```bash
git add app/daily.py tests/test_daily.py
git commit -m "feat: thread server scope through daily pick logic"
```

---

### Task 3: 排程器對個人 + 每個群組各建當日 pick

**Files:**
- Modify: `app/scheduler.py:9-13`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: Task 2 的 `get_or_create_today_pick(..., server=...)`、Task 1 的 `Membership` / `Server`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_scheduler.py` 末尾加：

```python
def test_daily_job_creates_personal_and_group_picks():
    import datetime
    from unittest.mock import patch
    from app.database import SessionLocal, init_db, engine, Base
    from app.models import User, Album, Server, Membership, DailyPick
    from app import scheduler
    Base.metadata.drop_all(bind=engine)
    init_db()
    with SessionLocal() as s:
        s.add(Album(title="A", artist="Art", year=2000))
        u = User(slug="u1"); srv = Server(slug="g1", name="g1")
        s.add_all([u, srv]); s.commit()
        s.add(Membership(user_id=u.id, server_id=srv.id)); s.commit()
    fixed = datetime.datetime(2026, 6, 21, 8, 30)

    class _DT(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    with patch.object(scheduler.datetime, "datetime", _DT):
        scheduler.run_daily_job()
    with SessionLocal() as s:
        picks = s.query(DailyPick).all()
        scopes = sorted([p.server_id for p in picks], key=lambda x: (x is not None, x))
        assert None in scopes          # 個人
        assert any(sid is not None for sid in scopes)  # 群組
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_scheduler.py::test_daily_job_creates_personal_and_group_picks -q`
Expected: FAIL（只建個人，沒有群組 pick）

- [ ] **Step 3: 改 scheduler.py**

```python
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
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_scheduler.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/scheduler.py tests/test_scheduler.py
git commit -m "feat: daily job creates picks for personal and each membership"
```

---

### Task 4: 情境中介層與 get_current_server 依賴

**Files:**
- Modify: `app/main.py:13`（匯入）、`app/main.py:42-60`（middleware + 依賴）
- Test: `tests/test_routes.py`

**Interfaces:**
- Produces: middleware 解析 `?g=` 寫入 `request.state.gid`，黏著 cookie `gid`；`?g=`（空）清除。
- Produces: `get_current_server(request, db, user) -> Server | None`（須為成員才回傳，否則 None）。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_routes.py` 末尾加（沿用該檔既有 `client` fixture / TestClient 模式；若該檔用 `from fastapi.testclient import TestClient`，比照）：

```python
def test_group_context_cookie_set_and_cleared(client):
    from app.database import SessionLocal
    from app.models import Server
    with SessionLocal() as s:
        s.add(Server(slug="gx", name="GX")); s.commit()
    # 帶 ?g= 設定群組情境 cookie
    r = client.get("/?g=gx")
    assert r.cookies.get("gid") == "gx" or "gid=gx" in r.headers.get("set-cookie", "")
    # 帶空 g 清除
    r2 = client.get("/?g=")
    sc = r2.headers.get("set-cookie", "")
    assert 'gid=""' in sc or "gid=;" in sc or "Max-Age=0" in sc
```

> 註：若既有 `tests/test_routes.py` 沒有 `client` fixture，改用檔內既有建立 TestClient 的方式（搜尋 `TestClient(`）。

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_routes.py::test_group_context_cookie_set_and_cleared -q`
Expected: FAIL（沒設/清 gid cookie）

- [ ] **Step 3: 改 main.py 匯入**

第 13 行改為：

```python
from app.models import User, Server, Membership, Album, DailyPick, DrawHistory, Comment
```

- [ ] **Step 4: 改 middleware（app/main.py:42-51）**

```python
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
            response.set_cookie("gid", incoming_g, max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax")
        else:
            response.delete_cookie("gid")
    return response
```

- [ ] **Step 5: 加 get_current_server 依賴（緊接在 get_current_user 之後）**

```python
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
```

- [ ] **Step 6: 跑測試確認通過**

Run: `python -m pytest tests/test_routes.py::test_group_context_cookie_set_and_cleared -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/main.py tests/test_routes.py
git commit -m "feat: group context middleware and get_current_server dependency"
```

---

### Task 5: 群組管理路由與頁面（建群 / 加入 / 暱稱）

**Files:**
- Modify: `app/main.py`（新增路由）
- Create: `app/templates/groups.html`
- Create: `app/templates/join.html`
- Modify: `app/templates/base.html:16-22`（導覽列加「群組」）
- Test: `tests/test_routes.py`

**Interfaces:**
- Consumes: Task 4 的 cookie 機制、Task 1 的 `Server` / `Membership`。
- Produces: `GET/POST /groups`、`POST /me`、`GET /s/{slug}`、`POST /s/{slug}/join`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_routes.py` 末尾加：

```python
def test_create_group_then_member_sees_group_home(client):
    r = client.post("/groups", data={"name": "Friends"}, follow_redirects=False)
    assert r.status_code == 303
    assert "gid=" in r.headers.get("set-cookie", "")
    # 建群後 /groups 列出該群
    page = client.get("/groups")
    assert "Friends" in page.text


def test_join_via_server_url(client):
    from app.database import SessionLocal
    from app.models import Server
    with SessionLocal() as s:
        s.add(Server(slug="open1", name="OpenGroup")); s.commit()
    # 非成員造訪 → 顯示加入頁
    page = client.get("/s/open1")
    assert "OpenGroup" in page.text
    # 加入
    r = client.post("/s/open1/join", follow_redirects=False)
    assert r.status_code == 303
    assert "gid=open1" in r.headers.get("set-cookie", "")


def test_set_name(client):
    client.get("/")  # 先建立使用者 cookie
    r = client.post("/me", data={"name": "Vic"}, follow_redirects=False)
    assert r.status_code == 303
    assert "Vic" in client.get("/groups").text
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_routes.py::test_create_group_then_member_sees_group_home tests/test_routes.py::test_join_via_server_url tests/test_routes.py::test_set_name -q`
Expected: FAIL（404 / 路由不存在）

- [ ] **Step 3: 加路由到 main.py（放在 home 之後、admin 之前任意處）**

```python
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
    resp.set_cookie("gid", server.slug, max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax")
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
        resp.set_cookie("gid", server.slug, max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax")
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
    resp.set_cookie("gid", server.slug, max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax")
    return resp
```

- [ ] **Step 4: 建 groups.html**

```html
{% extends "base.html" %}
{% block content %}
<h1>群組</h1>
<p><a href="/?g=">回到個人頁</a></p>

<h2>我的群組</h2>
<ul>
  {% for s in servers %}
    <li><a href="/?g={{ s.slug }}">{{ s.name }}</a>
        — 邀請連結：<code>/s/{{ s.slug }}</code></li>
  {% else %}
    <li>還沒有群組。</li>
  {% endfor %}
</ul>

<h2>建立群組</h2>
<form method="post" action="/groups">
  <input type="text" name="name" placeholder="群組名稱" required>
  <button type="submit">建立</button>
</form>

<h2>暱稱</h2>
<form method="post" action="/me">
  <input type="text" name="name" placeholder="顯示名稱" value="{{ me.name or '' }}">
  <button type="submit">儲存</button>
</form>
{% endblock %}
```

- [ ] **Step 5: 建 join.html**

```html
{% extends "base.html" %}
{% block content %}
<h1>加入「{{ server.name }}」？</h1>
<form method="post" action="/s/{{ server.slug }}/join">
  <button type="submit">加入</button>
</form>
<p><a href="/">取消</a></p>
{% endblock %}
```

- [ ] **Step 6: 導覽列加連結（base.html 的 nav 區塊）**

在 `<a href="/stats">統計</a>` 後加一行：

```html
      <a href="/groups">群組</a>
```

- [ ] **Step 7: 跑測試確認通過**

Run: `python -m pytest tests/test_routes.py -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add app/main.py app/templates/groups.html app/templates/join.html app/templates/base.html tests/test_routes.py
git commit -m "feat: group management routes and pages (create/join/name)"
```

---

### Task 6: 既有 view 依情境過濾 + 群組成員面板

**Files:**
- Modify: `app/main.py`（home / history / draw / draw_history / albums / album_detail / stats 加 server 依賴與過濾）
- Modify: `app/templates/index.html`（群組時顯示成員面板）
- Test: `tests/test_routes.py`、`tests/test_lifecycle.py`

**Interfaces:**
- Consumes: Task 2 的 `daily.scope`、`daily.server_members_today`、`daily.pending_gate_pick(..., server=)`、`get_current_today_pick(..., server=)`；Task 4 的 `get_current_server`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_routes.py` 末尾加：

```python
def test_history_scoped_to_group(client):
    # 建群並進入群組情境
    client.post("/groups", data={"name": "G"}, follow_redirects=False)
    # 群組情境下歷史與個人互不混（這裡只驗證頁面可開、不報錯）
    assert client.get("/history").status_code == 200
    assert client.get("/?g=").status_code in (200, 303)  # 切回個人
    assert client.get("/stats").status_code == 200
```

並在 `tests/test_lifecycle.py` 既有「個人完整流程」測試之外，加一個群組情境的最小生命週期測試（比照該檔既有風格：建 user/server/membership，跑 `daily.get_or_create_today_pick(..., server=srv)`，斷言 pick 的 `server_id == srv.id` 且 `pending_gate_pick(..., server=srv)` 行為正確）：

```python
def test_group_lifecycle_independent(client):
    import datetime
    from app.database import SessionLocal
    from app.models import User, Server, Membership
    from app import daily
    with SessionLocal() as s:
        u = s.query(User).first() or User(slug="lc1")
        if u.id is None:
            s.add(u); s.commit()
        srv = Server(slug="lc-g", name="LC")
        s.add(srv); s.commit()
        s.add(Membership(user_id=u.id, server_id=srv.id)); s.commit()
        now = datetime.datetime(2026, 6, 21, 8, 30)
        p = daily.get_or_create_today_pick(s, u, now.date(), now, server=srv)
        assert p.server_id == srv.id
        assert daily.get_or_create_today_pick(s, u, now.date(), now) .server_id is None
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_routes.py::test_history_scoped_to_group -q`
Expected: FAIL（view 尚未接 server，群組情境未生效 / 或 import 錯）

- [ ] **Step 3: 改 home（app/main.py:63-73）**

```python
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
```

- [ ] **Step 4: 改 history（app/main.py:150-160）**

加 `server` 依賴與過濾：

```python
@app.get("/history")
def history(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user), server: Server | None = Depends(get_current_server)):
    picks = (
        db.query(DailyPick)
        .filter(DailyPick.user_id == user.id, daily.scope(DailyPick.server_id, server))
        .order_by(DailyPick.date.desc())
        .all()
    )
    return templates.TemplateResponse(request, "history.html", {"picks": picks})
```

- [ ] **Step 5: 改 draw（app/main.py:163-181）**

```python
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
```

- [ ] **Step 6: 改 draw_history（app/main.py:184-192）**

```python
@app.get("/draw/history")
def draw_history(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user), server: Server | None = Depends(get_current_server)):
    records = (
        db.query(DrawHistory)
        .filter(DrawHistory.user_id == user.id, daily.scope(DrawHistory.server_id, server))
        .order_by(DrawHistory.drawn_at.desc())
        .all()
    )
    return templates.TemplateResponse(request, "draw_history.html", {"records": records})
```

- [ ] **Step 7: 改 albums 的 status 過濾（app/main.py:195-246）**

簽名加 `server: Server | None = Depends(get_current_server)`，並把 status 區塊的 picks 查詢加 scope：

```python
    if status:
        picks = db.query(DailyPick).filter(DailyPick.user_id == user.id, daily.scope(DailyPick.server_id, server)).all()
```

（其餘不變。）

- [ ] **Step 8: 改 album_detail（app/main.py:249-262）**

簽名加 `server` 依賴，picks 查詢加 scope：

```python
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
    return templates.TemplateResponse(request, "album_detail.html", {"album": album, "picks": picks})
```

- [ ] **Step 9: 改 stats（app/main.py:265-303）**

簽名加 `server` 依賴，並把所有 `DailyPick.user_id == user.id` 過濾各加一個 `daily.scope(DailyPick.server_id, server)`：

```python
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
```

- [ ] **Step 10: index.html 加成員面板**

在 `{% block content %}` 之後、`{% if gate %}` 之前插入：

```html
{% if server %}
  <p class="group-banner">群組：{{ server.name }} · <a href="/?g=">回個人頁</a></p>
  {% if members %}
  <details>
    <summary>成員今日進度（{{ members|length }}）</summary>
    <ul>
      {% for u, p in members %}
        <li>{{ u.name or u.slug[:6] }} —
          {% if p %}{{ p.album.artist }} · {{ p.status }}{% else %}尚未抽{% endif %}</li>
      {% endfor %}
    </ul>
  </details>
  {% endif %}
{% endif %}
```

- [ ] **Step 11: 跑全測試確認通過且無回歸**

Run: `python -m pytest -q`
Expected: PASS（全部，含既有 45 條）

- [ ] **Step 12: Commit**

```bash
git add app/main.py app/templates/index.html tests/test_routes.py tests/test_lifecycle.py
git commit -m "feat: scope all user views by server context + group members panel"
```

---

## 自審（spec 對照）

- **身分不加密碼** → 維持 cookie slug（Task 4 middleware 未動身分邏輯）✓
- **Server / Membership / User.name / server_id 欄位** → Task 1 ✓
- **每人各自抽、個人/群組獨立** → Task 2 測試 `test_personal_and_group_picks_are_independent` / `test_group_gate_independent_from_personal` ✓
- **互看成員** → Task 2 `server_members_today` + Task 6 成員面板 ✓
- **個人頁與群組頁並存** → `server=None` 為個人；既有路由不變，cookie 切換 ✓
- **方案 A 情境機制（?g= + cookie）** → Task 4 ✓
- **建群/加入/邀請=網址** → Task 5 ✓
- **遷移 SQLite/PG 不丟資料** → Task 1 Step 4/6 ✓
- **排程涵蓋個人+群組** → Task 3 ✓
- **既有 view 全部加範圍** → Task 6 涵蓋 home/history/draw/draw_history/albums/album_detail/stats ✓
- 型別一致性：`scope(col, server)`、`get_or_create_today_pick(db, user, today, now, server=None)` 全程一致 ✓
