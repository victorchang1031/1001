from urllib.parse import quote_plus


def apple_music_search_url(title: str, artist: str) -> str:
    term = quote_plus(f"{title} {artist}")
    return f"https://music.apple.com/search?term={term}"
