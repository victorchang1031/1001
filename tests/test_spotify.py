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
                        "name": "Kind of Blue",
                        "artists": [{"name": "Miles Davis"}],
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
            "results": [{
                "collectionName": "Kind of Blue",
                "artistName": "Miles Davis",
                "artworkUrl100": "https://is1-ssl.mzstatic.com/image/thumb/100x100bb.jpg",
            }]
        })

    client = _mock_client(handler)
    cover = spotify.itunes_cover_url(client, "Kind of Blue", "Miles Davis")
    assert cover == "https://is1-ssl.mzstatic.com/image/thumb/600x600bb.jpg"


def test_match_rejects_wrong_artist():
    def handler(request):
        return httpx.Response(200, json={
            "results": [{
                "collectionName": "Kind of Blue",
                "artistName": "Some Tribute Band",
                "artworkUrl100": "https://example/100x100.jpg",
            }]
        })

    cover = spotify.itunes_cover_url(_mock_client(handler), "Kind of Blue", "Miles Davis")
    assert cover is None


def test_deezer_cover_url_matches_and_returns_xl():
    def handler(request):
        return httpx.Response(200, json={"data": [{
            "title": "Kind of Blue",
            "artist": {"name": "Miles Davis"},
            "cover_xl": "https://e-cdns/cover_xl.jpg",
        }]})

    cover = spotify.deezer_cover_url(_mock_client(handler), "Kind of Blue", "Miles Davis")
    assert cover == "https://e-cdns/cover_xl.jpg"


def test_clean_query_keeps_parenthetical_only_title():
    assert spotify._clean_query_text("(Pronounced 'Leh-'Nerd 'Skin-'Nerd)") != ""


def test_musicbrainz_cover_url_via_coverart_archive():
    def handler(request):
        if "musicbrainz.org" in request.url.host:
            return httpx.Response(200, json={"releases": [{
                "id": "mbid-1", "title": "Zombie",
                "artist-credit": [{"name": "Fela Kuti"}],
            }]})
        if "coverartarchive.org" in request.url.host:
            return httpx.Response(200)  # front-500 exists
        return httpx.Response(404)

    cover = spotify.musicbrainz_cover_url(_mock_client(handler), "Zombie", "Fela Kuti")
    assert cover == "https://coverartarchive.org/release/mbid-1/front-500"


def test_musicbrainz_rejects_wrong_release():
    def handler(request):
        if "musicbrainz.org" in request.url.host:
            return httpx.Response(200, json={"releases": [{
                "id": "mbid-x", "title": "Totally Other Album",
                "artist-credit": [{"name": "Nobody"}],
            }]})
        return httpx.Response(200)

    cover = spotify.musicbrainz_cover_url(_mock_client(handler), "Zombie", "Fela Kuti")
    assert cover is None


def test_backfill_fills_missing_cover(monkeypatch):
    monkeypatch.setattr(spotify.settings, "spotify_client_id", None)
    monkeypatch.setattr(spotify.settings, "spotify_client_secret", None)

    def handler(request):
        return httpx.Response(200, json={"results": [{
            "collectionName": "X", "artistName": "Y",
            "artworkUrl100": "https://e/100x100.jpg",
        }]})

    with SessionLocal() as s:
        s.add(Album(title="X", artist="Y", year=2000))
        s.commit()
    spotify.backfill_missing_covers(sleep=0, client=_mock_client(handler))
    with SessionLocal() as s:
        a = s.query(Album).first()
        assert a.cover_image_url == "https://e/600x600.jpg"


def test_deezer_cover_url_rejects_mismatch():
    def handler(request):
        return httpx.Response(200, json={"data": [{
            "title": "Completely Different Album",
            "artist": {"name": "Other Artist"},
            "cover_xl": "https://e-cdns/wrong.jpg",
        }]})

    cover = spotify.deezer_cover_url(_mock_client(handler), "Kind of Blue", "Miles Davis")
    assert cover is None


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
