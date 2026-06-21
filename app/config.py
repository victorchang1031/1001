import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    spotify_client_id: str | None = os.getenv("SPOTIFY_CLIENT_ID") or None
    spotify_client_secret: str | None = os.getenv("SPOTIFY_CLIENT_SECRET") or None
    reveal_hour: int = 8
    random_seed: int = 42
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./app.db")


settings = Settings()
