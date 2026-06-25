import base64
import re
import threading
import time
from difflib import SequenceMatcher
from html import escape
import httpx
from app.config import settings
from app.models import Album

TOKEN_URL = "https://accounts.spotify.com/api/token"
SEARCH_URL = "https://api.spotify.com/v1/search"
DISCOGS_SEARCH_URL = "https://api.discogs.com/database/search"
ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
DEEZER_SEARCH_URL = "https://api.deezer.com/search/album"
MUSICBRAINZ_URL = "https://musicbrainz.org/ws/2/release/"
COVERART_URL = "https://coverartarchive.org"
_MB_UA = "DailyAlbum/1.0 ( victorchang891031@gmail.com )"

MATCH_THRESHOLD = 0.7


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _match_score(want_title: str, want_artist: str, got_title: str, got_artist: str) -> float:
    # ponytail: 藝人權重 0.5，錯藝人是最常見的錯封面；不夠準再調權重或門檻
    t = SequenceMatcher(None, _norm(want_title), _norm(got_title)).ratio()
    a = SequenceMatcher(None, _norm(want_artist), _norm(got_artist)).ratio()
    return 0.5 * t + 0.5 * a


def _pick_best(want_title: str, want_artist: str, candidates: list) -> object | None:
    # candidates: [(got_title, got_artist, payload), ...]，取最高分且過門檻者，否則 None
    best, best_score = None, 0.0
    for got_title, got_artist, payload in candidates:
        score = _match_score(want_title, want_artist, got_title, got_artist)
        if score > best_score:
            best, best_score = payload, score
    return best if best_score >= MATCH_THRESHOLD else None


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
    stripped = re.sub(r"\s*[\(\[][^)\]]*[\)\]]\s*$", "", text)
    if stripped.strip():  # 別把整個括號標題（如 "(Pronounced ...)"）刪成空字串
        text = stripped
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


def _spotify_query(client: httpx.Client, token: str, q: str, want_title: str, want_artist: str) -> dict | None:
    resp = client.get(
        SEARCH_URL,
        headers={"Authorization": f"Bearer {token}"},
        params={"q": q, "type": "album", "limit": 5},
    )
    resp.raise_for_status()
    items = resp.json().get("albums", {}).get("items", [])
    candidates = []
    for item in items:
        images = item.get("images") or []
        got_artist = ", ".join(a.get("name", "") for a in item.get("artists", []))
        candidates.append((item.get("name", ""), got_artist, {
            "url": item.get("external_urls", {}).get("spotify"),
            "image": images[0].get("url") if images else None,
        }))
    return _pick_best(want_title, want_artist, candidates)


def search_album(client: httpx.Client, token: str, title: str, artist: str) -> dict | None:
    title, artist = _clean_query_text(title), _clean_query_text(artist)
    try:
        result = _retry(lambda: _spotify_query(client, token, f"album:{title} artist:{artist}", title, artist))
        if result:
            return result
        return _retry(lambda: _spotify_query(client, token, title, title, artist))
    except (httpx.HTTPError, ValueError):
        return None


def _discogs_query(client: httpx.Client, headers: dict, params: dict, want_title: str, want_artist: str) -> str | None:
    resp = client.get(DISCOGS_SEARCH_URL, headers=headers, params=params)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    # Discogs 的 title 是 "Artist - Title" 合併字串，直接整串比對
    want = _norm(f"{want_artist} {want_title}")
    best, best_score = None, 0.0
    for r in results:
        cover = r.get("cover_image") or r.get("thumb")
        # ponytail: Discogs returns a 1x1 spacer.gif placeholder when a release has no real image
        if not cover or "spacer.gif" in cover:
            continue
        score = SequenceMatcher(None, want, _norm(r.get("title", ""))).ratio()
        if score > best_score:
            best, best_score = cover, score
    return best if best_score >= MATCH_THRESHOLD else None


def discogs_cover_url(client: httpx.Client, title: str, artist: str) -> str | None:
    title, artist = _clean_query_text(title), _clean_query_text(artist)
    headers = {"User-Agent": "DailyAlbum/1.0"}
    if settings.discogs_token:
        headers["Authorization"] = f"Discogs token={settings.discogs_token}"
    try:
        cover = _retry(lambda: _discogs_query(
            client, headers, {"release_title": title, "artist": artist, "type": "release", "per_page": 5}, title, artist
        ))
        if cover:
            return cover
        return _retry(lambda: _discogs_query(
            client, headers, {"q": f"{artist} {title}", "type": "release", "per_page": 5}, title, artist
        ))
    except (httpx.HTTPError, ValueError):
        return None


def _deezer_query(client: httpx.Client, params: dict, want_title: str, want_artist: str) -> str | None:
    resp = client.get(DEEZER_SEARCH_URL, params=params)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    candidates = [
        (r.get("title", ""), r.get("artist", {}).get("name", ""), r.get("cover_xl") or r.get("cover_big"))
        for r in data
    ]
    return _pick_best(want_title, want_artist, candidates)


def deezer_cover_url(client: httpx.Client, title: str, artist: str) -> str | None:
    # ponytail: 免 key、免 token、覆蓋率高；放在 iTunes 之後、Discogs 之前
    title, artist = _clean_query_text(title), _clean_query_text(artist)
    try:
        return _retry(lambda: _deezer_query(client, {"q": f"{artist} {title}", "limit": 5}, title, artist))
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


def _itunes_query(client: httpx.Client, params: dict, want_title: str, want_artist: str) -> str | None:
    resp = client.get(ITUNES_SEARCH_URL, params=params)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    candidates = []
    for r in results:
        art = r.get("artworkUrl100")
        image = art.replace("100x100", "600x600") if art else None
        candidates.append((r.get("collectionName", ""), r.get("artistName", ""), image))
    return _pick_best(want_title, want_artist, candidates)


def itunes_cover_url(client: httpx.Client, title: str, artist: str) -> str | None:
    # ponytail: no API key needed, free, high hit rate; try before Discogs
    title, artist = _clean_query_text(title), _clean_query_text(artist)
    try:
        return _retry(lambda: _itunes_query(
            client, {"term": f"{artist} {title}", "entity": "album", "limit": 5}, title, artist
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


def _caa_front(client: httpx.Client, kind: str, mbid: str) -> str | None:
    url = f"{COVERART_URL}/{kind}/{mbid}/front-500"
    r = client.get(url, headers={"User-Agent": _MB_UA}, follow_redirects=True)
    return url if r.status_code == 200 else None


def _musicbrainz_query(client: httpx.Client, title: str, artist: str) -> str | None:
    resp = client.get(MUSICBRAINZ_URL, headers={"User-Agent": _MB_UA}, params={
        "query": f'release:"{title}" AND artist:"{artist}"', "fmt": "json", "limit": 5,
    })
    resp.raise_for_status()
    for rel in resp.json().get("releases", []):
        got_artist = (rel.get("artist-credit") or [{}])[0].get("name", "")
        if _match_score(title, artist, rel.get("title", ""), got_artist) < MATCH_THRESHOLD:
            continue
        # release 沒圖時退而求其次找整個 release-group 的封面
        cover = _caa_front(client, "release", rel["id"])
        if cover:
            return cover
        rg = (rel.get("release-group") or {}).get("id")
        if rg:
            cover = _caa_front(client, "release-group", rg)
            if cover:
                return cover
    return None


def musicbrainz_cover_url(client: httpx.Client, title: str, artist: str) -> str | None:
    # ponytail: 權威庫、免 key，但慢且限流 1req/s，所以放最後一棒、只給前面都沒中的少數用
    title, artist = _clean_query_text(title), _clean_query_text(artist)
    try:
        return _retry(lambda: _musicbrainz_query(client, title, artist))
    except (httpx.HTTPError, ValueError):
        return None


def backfill_missing_covers(sleep: float = 0.2, client: httpx.Client | None = None, max_passes: int = 3) -> int:
    # 補所有缺圖／只有 placeholder 的專輯；已有真實封面的會被 filter 排除，重啟不重抓。
    # 多跑幾輪：首輪大量抓取常被限流而留下 placeholder，後續輪只處理剩下的少數，
    # 不會再限流；沒進展就停（剩的是真的難匹配的）。
    from app.database import SessionLocal
    own_client = client is None
    client = client or httpx.Client(timeout=10)
    db = SessionLocal()
    missing = Album.cover_image_url.is_(None) | Album.cover_image_url.like("data:%")
    filled = 0
    try:
        prev_remaining = None
        for _ in range(max_passes):
            albums = db.query(Album).filter(missing).all()
            if not albums:
                break
            for album in albums:
                album.spotify_url = None
                album.cover_image_url = None
                try:
                    ensure_spotify_url(db, album, client)
                except Exception:
                    db.rollback()
                time.sleep(sleep)
            remaining = db.query(Album).filter(missing).count()
            filled += len(albums) - remaining
            if remaining == prev_remaining:
                break
            prev_remaining = remaining
        return filled
    finally:
        db.close()
        if own_client:
            client.close()


def start_cover_backfill() -> None:
    # ponytail: daemon 執行緒在背景補圖，不擋 web server 啟動（Render 啟動有逾時）
    threading.Thread(target=backfill_missing_covers, daemon=True).start()


def _ensure_cover_fallback(db, album: Album, client: httpx.Client | None) -> None:
    own_client = client is None
    client = client or httpx.Client()
    try:
        cover = (
            itunes_cover_url(client, album.title, album.artist)
            or deezer_cover_url(client, album.title, album.artist)
            or discogs_cover_url(client, album.title, album.artist)
            or musicbrainz_cover_url(client, album.title, album.artist)
        )
        album.cover_image_url = cover or _placeholder_cover_url(album.title, album.artist)
        db.commit()
    finally:
        if own_client:
            client.close()
