from app.models import Album

SAMPLE_ALBUMS = [
    {"title": "Kind of Blue", "artist": "Miles Davis", "year": 1959, "genre": "Jazz"},
    {"title": "Pet Sounds", "artist": "The Beach Boys", "year": 1966, "genre": "Pop"},
    {"title": "Revolver", "artist": "The Beatles", "year": 1966, "genre": "Rock"},
    {"title": "The Velvet Underground & Nico", "artist": "The Velvet Underground", "year": 1967, "genre": "Rock"},
    {"title": "What's Going On", "artist": "Marvin Gaye", "year": 1971, "genre": "Soul"},
    {"title": "The Dark Side of the Moon", "artist": "Pink Floyd", "year": 1973, "genre": "Rock"},
    {"title": "Innervisions", "artist": "Stevie Wonder", "year": 1973, "genre": "Soul"},
    {"title": "Rumours", "artist": "Fleetwood Mac", "year": 1977, "genre": "Rock"},
    {"title": "London Calling", "artist": "The Clash", "year": 1979, "genre": "Punk"},
    {"title": "Thriller", "artist": "Michael Jackson", "year": 1982, "genre": "Pop"},
    {"title": "Purple Rain", "artist": "Prince", "year": 1984, "genre": "Pop"},
    {"title": "The Queen Is Dead", "artist": "The Smiths", "year": 1986, "genre": "Rock"},
    {"title": "Paul's Boutique", "artist": "Beastie Boys", "year": 1989, "genre": "Hip Hop"},
    {"title": "Nevermind", "artist": "Nirvana", "year": 1991, "genre": "Rock"},
    {"title": "OK Computer", "artist": "Radiohead", "year": 1997, "genre": "Rock"},
]


def seed_albums(db) -> int:
    if db.query(Album).count() > 0:
        return 0
    for a in SAMPLE_ALBUMS:
        db.add(Album(**a))
    db.commit()
    return len(SAMPLE_ALBUMS)
