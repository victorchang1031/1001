import httpx
from app.music_links import wikipedia_search_url, wikipedia_url


def test_wikipedia_search_url_encodes_term():
    url = wikipedia_search_url("Kind of Blue", "Miles Davis")
    assert url.startswith("https://en.wikipedia.org/w/index.php?search=")
    assert "Kind" in url and "Miles" in url
    assert " " not in url  # 空白需編碼


def test_wikipedia_url_uses_opensearch_match():
    def handler(request):
        return httpx.Response(200, json=[
            "Kind of Blue Miles Davis",
            ["Kind of Blue (Miles Davis album)"],
            [""],
            ["https://en.wikipedia.org/wiki/Kind_of_Blue_(Miles_Davis_album)"],
        ])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    url = wikipedia_url("Kind of Blue", "Miles Davis", client)
    assert url == "https://en.wikipedia.org/wiki/Kind_of_Blue_(Miles_Davis_album)"


def test_wikipedia_url_falls_back_to_search_when_no_match():
    def handler(request):
        return httpx.Response(200, json=["x", [], [], []])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    url = wikipedia_url("Some Obscure Album", "Some Artist", client)
    assert url.startswith("https://en.wikipedia.org/w/index.php?search=")


def test_wikipedia_url_falls_back_on_network_error():
    def handler(request):
        raise httpx.ConnectError("boom")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    url = wikipedia_url("Some Album", "Some Artist", client)
    assert url.startswith("https://en.wikipedia.org/w/index.php?search=")
