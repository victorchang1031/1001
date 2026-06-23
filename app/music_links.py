from urllib.parse import quote_plus
import httpx

OPENSEARCH_URL = "https://en.wikipedia.org/w/api.php"


def wikipedia_search_url(title: str, artist: str) -> str:
    term = quote_plus(f"{title} {artist}")
    return f"https://en.wikipedia.org/w/index.php?search={term}"


def wikipedia_url(title: str, artist: str, client: httpx.Client | None = None) -> str:
    # ponytail: opensearch finds the actual article title so the link jumps
    # straight to the page; falls back to a search link if no match/network error
    own_client = client is None
    client = client or httpx.Client(timeout=5)
    try:
        resp = client.get(OPENSEARCH_URL, params={
            "action": "opensearch", "search": f"{title} {artist}", "limit": 1, "format": "json",
        })
        resp.raise_for_status()
        urls = resp.json()[3]
        return urls[0] if urls else wikipedia_search_url(title, artist)
    except (httpx.HTTPError, ValueError, IndexError):
        return wikipedia_search_url(title, artist)
    finally:
        if own_client:
            client.close()
