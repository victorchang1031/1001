import httpx
from app.database import SessionLocal, init_db, engine, Base
from app.models import Album
from app import spotify


def setup_function():
    Base.metadata.drop_all(bind=engine)
    init_db()
    spotify._token_cache.update(token=None, expires_at=0.0)


def _mock_client(handler):
    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport)


def test_search_album_returns_url_and_image(monkeypatch):
    monkeypatch.setattr(spotify.settings, "spotify_client_id", "client_id")
    monkeypatch.setattr(spotify.settings, "spotify_client_secret", "client_secret")
    def handler(request):
        if request.url.path == "/api/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if request.url.path == "/v1/search":
            return httpx.Response(200, json={
                "albums": {"items": [
                    {
                        "external_urls": {"spotify": "https://open.spotify.com/album/xyz"},
                        "images": [{"url": "https://i.scdn.co/image/cover.jpg"}],
                    }
                ]}
            })
        return httpx.Response(404)

    client = _mock_client(handler)
    token = spotify.get_access_token(client)
    assert token == "tok"
    result = spotify.search_album(client, token, "Kind of Blue", "Miles Davis")
    assert result["url"] == "https://open.spotify.com/album/xyz"
    assert result["image"] == "https://i.scdn.co/image/cover.jpg"


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


def test_itunes_cover_url_returns_high_res_artwork():
    def handler(request):
        return httpx.Response(200, json={
            "results": [{"artworkUrl100": "https://is1-ssl.mzstatic.com/image/thumb/100x100bb.jpg"}]
        })

    client = _mock_client(handler)
    cover = spotify.itunes_cover_url(client, "Kind of Blue", "Miles Davis")
    assert cover == "https://is1-ssl.mzstatic.com/image/thumb/600x600bb.jpg"


def test_cover_image_always_set_even_when_all_lookups_fail(monkeypatch):
    monkeypatch.setattr(spotify.settings, "spotify_client_id", None)
    monkeypatch.setattr(spotify.settings, "spotify_client_secret", None)

    def handler(request):
        return httpx.Response(404)

    with SessionLocal() as s:
        a = Album(title="X", artist="Y", year=2000)
        s.add(a)
        s.commit()
        spotify.ensure_spotify_url(s, a, client=_mock_client(handler))
        assert a.cover_image_url is not None
        assert a.cover_image_url.startswith("data:image/svg+xml;base64,")
