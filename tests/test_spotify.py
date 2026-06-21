import httpx
from app.database import SessionLocal, init_db, engine, Base
from app.models import Album
from app import spotify


def setup_function():
    Base.metadata.drop_all(bind=engine)
    init_db()


def _mock_client(handler):
    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport)


def test_search_album_url_returns_external_url(monkeypatch):
    monkeypatch.setattr(spotify.settings, "spotify_client_id", "client_id")
    monkeypatch.setattr(spotify.settings, "spotify_client_secret", "client_secret")
    def handler(request):
        if request.url.path == "/api/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if request.url.path == "/v1/search":
            return httpx.Response(200, json={
                "albums": {"items": [
                    {"external_urls": {"spotify": "https://open.spotify.com/album/xyz"}}
                ]}
            })
        return httpx.Response(404)

    client = _mock_client(handler)
    token = spotify.get_access_token(client)
    assert token == "tok"
    url = spotify.search_album_url(client, token, "Kind of Blue", "Miles Davis")
    assert url == "https://open.spotify.com/album/xyz"


def test_ensure_spotify_url_uses_cache():
    with SessionLocal() as s:
        a = Album(title="X", artist="Y", year=2000, spotify_url="https://cached")
        s.add(a)
        s.commit()
        # 不傳 client，已快取應直接回傳
        assert spotify.ensure_spotify_url(s, a) == "https://cached"


def test_ensure_spotify_url_none_when_no_credentials(monkeypatch):
    monkeypatch.setattr(spotify.settings, "spotify_client_id", None)
    monkeypatch.setattr(spotify.settings, "spotify_client_secret", None)
    with SessionLocal() as s:
        a = Album(title="X", artist="Y", year=2000)
        s.add(a)
        s.commit()
        assert spotify.ensure_spotify_url(s, a) is None
