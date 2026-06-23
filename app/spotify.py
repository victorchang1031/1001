import base64
import re
import time
from html import escape
import httpx
from app.config import settings
from app.models import Album

TOKEN_URL = "https://accounts.spotify.com/api/token"
SEARCH_URL = "https://api.spotify.com/v1/search"
DISCOGS_SEARCH_URL = "https://api.discogs.com/database/search"
ITUNES_SEARCH_URL = "https://itunes.apple.com/search"


def _retry(fn):
    # ponytail: one retry after a short pause covers transient 429/5xx/timeouts;
    # exponential backoff only if a single retry still isn't enough in practice.
    try:
        return fn()
    except (httpx.HTTPError, ValueError):
        time.sleep(0.5)
        return fn()


def _clean_query_text(text: str) -> str:
    # ponytail: strip "(...)" suffixes and "Artist, The" / Discogs "*" noise so
    # search strings match real release titles more often; richer fuzzy matching
    # (Levenshtein, alternate-title retry) only if this still misses a lot.
    text = re.sub(r"\s*[\(\[][^)\]]*[\)\]]\s*$", "", text)
    text = text.replace("*", "")
    text = re.sub(r"^(.+),\s*The$", r"The \1", text.strip())
    return text.split("/")[0].strip()


_token_cache: dict[str, float | str | None] = {"token": None, "expires_at": 0.0}


def get_access_token(client: httpx.Client) -> str | None:
    # ponytail: cache the token in-process instead of refetching per album;
    # avoids tripping Spotify's auth-endpoint rate limit on bulk fetches
    if _token_cache["token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["token"]
    if not settings.spotify_client_id or not settings.spotify_client_secret:
        return None
    auth = base64.b64encode(
        f"{settings.spotify_client_id}:{settings.spotify_client_secret}".encode()
    ).decode()
    def fetch():
        resp = client.post(
            TOKEN_URL,
            headers={"Authorization": f"Basic {auth}"},
            data={"grant_type": "client_credentials"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("access_token"), data.get("expires_in", 3600)

    try:
        token, expires_in = _retry(fetch)
        _token_cache["token"] = token
        _token_cache["expires_at"] = time.time() + expires_in - 60
        return token
    except (httpx.HTTPError, ValueError):
        return None


def _spotify_query(client: httpx.Client, token: str, q: str) -> dict | None:
    resp = client.get(
        SEARCH_URL,
        headers={"Authorization": f"Bearer {token}"},
        params={"q": q, "type": "album", "limit": 1},
    )
    resp.raise_for_status()
    items = resp.json().get("albums", {}).get("items", [])
    if not items:
        return None
    item = items[0]
    images = item.get("images") or []
    return {
        "url": item.get("external_urls", {}).get("spotify"),
        "image": images[0].get("url") if images else None,
    }


def search_album(client: httpx.Client, token: str, title: str, artist: str) -> dict | None:
    title, artist = _clean_query_text(title), _clean_query_text(artist)
    try:
        result = _retry(lambda: _spotify_query(client, token, f"album:{title} artist:{artist}"))
        if result:
            return result
        return _retry(lambda: _spotify_query(client, token, title))
    except (httpx.HTTPError, ValueError):
        return None


def _discogs_query(client: httpx.Client, headers: dict, params: dict) -> str | None:
    resp = client.get(DISCOGS_SEARCH_URL, headers=headers, params=params)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    if not results:
        return None
    cover = results[0].get("cover_image") or results[0].get("thumb") or None
    # ponytail: Discogs returns a 1x1 spacer.gif placeholder when a release has no real image
    return None if cover and "spacer.gif" in cover else cover


def discogs_cover_url(client: httpx.Client, title: str, artist: str) -> str | None:
    title, artist = _clean_query_text(title), _clean_query_text(artist)
    headers = {"User-Agent": "DailyAlbum/1.0"}
    if settings.discogs_token:
        headers["Authorization"] = f"Discogs token={settings.discogs_token}"
    try:
        cover = _retry(lambda: _discogs_query(
            client, headers, {"release_title": title, "artist": artist, "type": "release", "per_page": 1}
        ))
        if cover:
            return cover
        return _retry(lambda: _discogs_query(client, headers, {"q": f"{artist} {title}", "type": "release", "per_page": 1}))
    except (httpx.HTTPError, ValueError):
        return None


def ensure_spotify_url(db, album: Album, client: httpx.Client | None = None) -> str | None:
    if album.spotify_url:
        if not album.cover_image_url:
            _ensure_cover_fallback(db, album, client)
        return album.spotify_url
    if not settings.spotify_client_id or not settings.spotify_client_secret:
        _ensure_cover_fallback(db, album, client)
        return None
    own_client = client is None
    client = client or httpx.Client()
    try:
        token = get_access_token(client)
        if not token:
            _ensure_cover_fallback(db, album, client)
            return None
        result = search_album(client, token, album.title, album.artist)
        if result:
            album.spotify_url = result["url"]
            album.cover_image_url = result["image"]
            db.commit()
        if not album.cover_image_url:
            _ensure_cover_fallback(db, album, client)
        return result["url"] if result else None
    finally:
        if own_client:
            client.close()


def _itunes_query(client: httpx.Client, params: dict) -> str | None:
    resp = client.get(ITUNES_SEARCH_URL, params=params)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    if not results:
        return None
    art = results[0].get("artworkUrl100")
    return art.replace("100x100", "600x600") if art else None


def itunes_cover_url(client: httpx.Client, title: str, artist: str) -> str | None:
    # ponytail: no API key needed, free, high hit rate; try before Discogs
    title, artist = _clean_query_text(title), _clean_query_text(artist)
    try:
        return _retry(lambda: _itunes_query(
            client, {"term": f"{artist} {title}", "entity": "album", "limit": 1}
        ))
    except (httpx.HTTPError, ValueError):
        return None


def _placeholder_cover_url(title: str, artist: str) -> str:
    # ponytail: local data-URI SVG, no network call, so this fallback can never fail
    label = escape((artist or title)[:24])
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="480" height="480">'
        '<rect width="100%" height="100%" fill="#333"/>'
        f'<text x="50%" y="50%" font-size="28" fill="#eee" text-anchor="middle" '
        f'dominant-baseline="middle" font-family="sans-serif">{label}</text></svg>'
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def _ensure_cover_fallback(db, album: Album, client: httpx.Client | None) -> None:
    own_client = client is None
    client = client or httpx.Client()
    try:
        cover = itunes_cover_url(client, album.title, album.artist) or discogs_cover_url(client, album.title, album.artist)
        album.cover_image_url = cover or _placeholder_cover_url(album.title, album.artist)
        db.commit()
    finally:
        if own_client:
            client.close()
