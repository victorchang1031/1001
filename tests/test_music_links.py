from app.music_links import apple_music_search_url


def test_apple_music_search_url_encodes_term():
    url = apple_music_search_url("Kind of Blue", "Miles Davis")
    assert url.startswith("https://music.apple.com/search?term=")
    assert "Kind" in url and "Miles" in url
    assert " " not in url  # 空白需編碼
