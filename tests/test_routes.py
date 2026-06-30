import datetime
from fastapi.testclient import TestClient
from app.database import init_db, engine, Base, SessionLocal
from app.models import Album, Server, User, Membership, DailyPick, Comment


def setup_module(module):
    Base.metadata.drop_all(bind=engine)
    init_db()
    with SessionLocal() as s:
        s.add(Album(title="Kind of Blue", artist="Miles Davis", year=1959, genre="Jazz"))
        s.add(Album(title="Thriller", artist="Michael Jackson", year=1982, genre="Pop"))
        s.commit()


def _client():
    from app.main import app
    return TestClient(app)


def test_home_returns_200():
    r = _client().get("/")
    assert r.status_code == 200


def test_albums_page_lists_and_filters():
    c = _client()
    r = c.get("/albums")
    assert r.status_code == 200
    assert "Kind of Blue" in r.text
    r2 = c.get("/albums", params={"genre": "Pop"})
    assert "Thriller" in r2.text
    assert "Kind of Blue" not in r2.text


def test_history_page_returns_200():
    r = _client().get("/history")
    assert r.status_code == 200


def test_draw_returns_album_and_records_history():
    from app.models import DrawHistory
    r = _client().get("/draw")
    assert r.status_code == 200
    with SessionLocal() as s:
        assert s.query(DrawHistory).count() == 1


def test_draw_history_page_lists_records():
    c = _client()
    c.get("/draw")
    r = c.get("/draw/history")
    assert r.status_code == 200
    assert "Kind of Blue" in r.text or "Thriller" in r.text


def test_albums_page_search():
    c = _client()
    r = c.get("/albums", params={"q": "Thriller"})
    assert "Thriller" in r.text
    assert "Kind of Blue" not in r.text


def test_album_detail_returns_200():
    with SessionLocal() as s:
        album = s.query(Album).filter_by(title="Kind of Blue").first()
        album_id = album.id
    r = _client().get(f"/albums/{album_id}")
    assert r.status_code == 200
    assert "Kind of Blue" in r.text


def test_album_detail_404_for_missing_album():
    r = _client().get("/albums/999999")
    assert r.status_code == 404


def test_stats_page_returns_200():
    r = _client().get("/stats")
    assert r.status_code == 200
    assert "專輯總數" in r.text


def test_group_context_cookie_set_and_cleared():
    with SessionLocal() as s:
        s.add(Server(slug="gx", name="GX"))
        s.commit()
    c = _client()
    r = c.get("/?g=gx")
    assert r.cookies.get("gid") == "gx" or "gid=gx" in r.headers.get("set-cookie", "")
    r2 = c.get("/?g=")
    sc = r2.headers.get("set-cookie", "")
    assert 'gid=""' in sc or "gid=;" in sc or "Max-Age=0" in sc


def test_create_group_then_member_sees_group_home():
    c = _client()
    r = c.post("/groups", data={"name": "Friends"}, follow_redirects=False)
    assert r.status_code == 303
    assert "gid=" in r.headers.get("set-cookie", "")
    page = c.get("/groups")
    assert "Friends" in page.text


def test_join_via_server_url():
    with SessionLocal() as s:
        s.add(Server(slug="open1", name="OpenGroup"))
        s.commit()
    c = _client()
    page = c.get("/s/open1")
    assert "OpenGroup" in page.text
    r = c.post("/s/open1/join", data={"name": "Vic"}, follow_redirects=False)
    assert r.status_code == 303
    assert "gid=open1" in r.headers.get("set-cookie", "")


def test_set_name():
    c = _client()
    c.get("/")
    r = c.post("/me", data={"name": "Vic"}, follow_redirects=False)
    assert r.status_code == 303
    assert "Vic" in c.get("/groups").text


def test_history_scoped_to_group():
    c = _client()
    c.post("/groups", data={"name": "G"}, follow_redirects=False)
    assert c.get("/history").status_code == 200
    assert c.get("/draw").status_code == 200
    assert c.get("/draw/history").status_code == 200
    assert c.get("/albums", params={"status": "listened"}).status_code == 200
    assert c.get("/stats").status_code == 200
    home = c.get("/")
    assert home.status_code == 200
    assert "群組" in home.text
    r2 = c.get("/?g=", follow_redirects=False)
    assert r2.status_code in (200, 303)


def test_personal_and_group_history_independent_at_data_layer():
    with SessionLocal() as s:
        s.add(Server(slug="hist-g", name="HistG"))
        s.commit()
    c = _client()
    c.get("/draw")
    r = c.post("/s/hist-g/join", data={"name": "Vic"}, follow_redirects=False)
    assert r.status_code == 303
    c.get("/draw")
    with SessionLocal() as s:
        from app.models import DrawHistory
        personal_draws = (
            s.query(DrawHistory).filter(DrawHistory.server_id.is_(None)).count()
        )
        group_draws = (
            s.query(DrawHistory)
            .join(Server, Server.id == DrawHistory.server_id)
            .filter(Server.slug == "hist-g")
            .count()
        )
        assert personal_draws >= 1
        assert group_draws == 1


def _seed_group_comment(album_id, server_slug, commenter_slug):
    with SessionLocal() as s:
        srv = Server(slug=server_slug, name=server_slug)
        commenter = User(slug=commenter_slug, name=commenter_slug)
        s.add_all([srv, commenter])
        s.commit()
        s.add(Membership(user_id=commenter.id, server_id=srv.id))
        pick = DailyPick(
            user_id=commenter.id, server_id=srv.id,
            date=datetime.date(2026, 6, 21), album_id=album_id,
            status="listened", revealed_at=datetime.datetime(2026, 6, 21, 8, 30),
        )
        s.add(pick)
        s.commit()
        s.add(Comment(daily_pick_id=pick.id, content="great album", rating=5,
                       created_at=datetime.datetime(2026, 6, 21, 9, 0)))
        s.commit()


def test_album_detail_shows_other_group_members_comments():
    with SessionLocal() as s:
        album_id = s.query(Album).filter_by(title="Kind of Blue").first().id
    _seed_group_comment(album_id, "grp-album", "commenter1")
    c = _client()
    c.get("/?u=viewer1")
    c.post("/s/grp-album/join", data={"name": "Viewer1"})
    r = c.get(f"/albums/{album_id}")
    assert "great album" in r.text
    assert "commenter1" in r.text


def test_activity_page_lists_group_members_comments():
    with SessionLocal() as s:
        album_id = s.query(Album).filter_by(title="Kind of Blue").first().id
    _seed_group_comment(album_id, "grp-activity", "commenter2")
    c = _client()
    c.get("/?u=viewer2")
    c.post("/s/grp-activity/join", data={"name": "Viewer2"})
    r = c.get("/activity")
    assert r.status_code == 200
    assert "great album" in r.text
    assert "commenter2" in r.text


def test_home_page_shows_group_comments():
    with SessionLocal() as s:
        album_id = s.query(Album).filter_by(title="Kind of Blue").first().id
    _seed_group_comment(album_id, "grp-home", "commenter4")
    c = _client()
    c.get("/?u=viewer4")
    c.post("/s/grp-home/join", data={"name": "Viewer4"})
    r = c.get("/")
    assert "great album" in r.text
    assert "commenter4" in r.text


def test_activity_personal_mode_hides_other_users_comments():
    with SessionLocal() as s:
        album_id = s.query(Album).filter_by(title="Kind of Blue").first().id
    _seed_group_comment(album_id, "grp-private", "commenter3")
    c = _client()
    c.get("/?u=viewer3")
    r = c.get("/activity")
    assert "great album" not in r.text
