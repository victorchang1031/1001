import base64
import httpx
from app.config import settings
from app.models import Album

TOKEN_URL = "https://accounts.spotify.com/api/token"
SEARCH_URL = "https://api.spotify.com/v1/search"


def get_access_token(client: httpx.Client) -> str | None:
    if not settings.spotify_client_id or not settings.spotify_client_secret:
        return None
    auth = base64.b64encode(
        f"{settings.spotify_client_id}:{settings.spotify_client_secret}".encode()
    ).decode()
    try:
        resp = client.post(
            TOKEN_URL,
            headers={"Authorization": f"Basic {auth}"},
            data={"grant_type": "client_credentials"},
        )
        resp.raise_for_status()
        return resp.json().get("access_token")
    except (httpx.HTTPError, ValueError):
        return None


def search_album_url(client: httpx.Client, token: str, title: str, artist: str) -> str | None:
    try:
        resp = client.get(
            SEARCH_URL,
            headers={"Authorization": f"Bearer {token}"},
            params={"q": f"album:{title} artist:{artist}", "type": "album", "limit": 1},
        )
        resp.raise_for_status()
        items = resp.json().get("albums", {}).get("items", [])
        if not items:
            return None
        return items[0].get("external_urls", {}).get("spotify")
    except (httpx.HTTPError, ValueError):
        return None


def ensure_spotify_url(db, album: Album, client: httpx.Client | None = None) -> str | None:
    if album.spotify_url:
        return album.spotify_url
    if not settings.spotify_client_id or not settings.spotify_client_secret:
        return None
    own_client = client is None
    client = client or httpx.Client()
    try:
        token = get_access_token(client)
        if not token:
            return None
        url = search_album_url(client, token, album.title, album.artist)
        if url:
            album.spotify_url = url
            db.commit()
        return url
    finally:
        if own_client:
            client.close()
