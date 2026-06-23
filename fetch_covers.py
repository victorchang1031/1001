"""一次性腳本：抓取所有缺少封面圖的專輯封面（執行：python fetch_covers.py）"""
import sys
import time
import httpx

sys.stdout.reconfigure(encoding="utf-8")
from app.database import SessionLocal, init_db
from app.models import Album
from app.spotify import ensure_spotify_url

init_db()
db = SessionLocal()
with httpx.Client(timeout=10, verify=False) as client:  # ponytail: 這台機器 CA 信任鏈壞了，修好後移除
    albums = db.query(Album).filter(
        Album.cover_image_url.is_(None) | Album.cover_image_url.like("data:%")
    ).all()
    for i, album in enumerate(albums, 1):
        album.spotify_url = None
        album.cover_image_url = None
        ensure_spotify_url(db, album, client)
        print(f"[{i}/{len(albums)}] {album.artist} - {album.title}: {album.cover_image_url}")
        time.sleep(0.2)
db.close()
