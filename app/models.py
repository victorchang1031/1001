import datetime
from sqlalchemy import ForeignKey, String, Integer, Date, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Album(Base):
    __tablename__ = "album"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String)
    artist: Mapped[str] = mapped_column(String)
    year: Mapped[int] = mapped_column(Integer)
    genre: Mapped[str | None] = mapped_column(String, nullable=True)
    spotify_url: Mapped[str | None] = mapped_column(String, nullable=True)
    apple_music_url: Mapped[str | None] = mapped_column(String, nullable=True)


class QueueEntry(Base):
    __tablename__ = "queue_entry"
    id: Mapped[int] = mapped_column(primary_key=True)
    album_id: Mapped[int] = mapped_column(ForeignKey("album.id"))
    position: Mapped[int] = mapped_column(Integer)
    album: Mapped["Album"] = relationship()


class DailyPick(Base):
    __tablename__ = "daily_pick"
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[datetime.date] = mapped_column(Date, unique=True)
    album_id: Mapped[int] = mapped_column(ForeignKey("album.id"))
    status: Mapped[str] = mapped_column(String, default="pending")
    revealed_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    album: Mapped["Album"] = relationship()
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="daily_pick", cascade="all, delete-orphan"
    )


class Comment(Base):
    __tablename__ = "comment"
    id: Mapped[int] = mapped_column(primary_key=True)
    daily_pick_id: Mapped[int] = mapped_column(ForeignKey("daily_pick.id"))
    content: Mapped[str] = mapped_column(String)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    daily_pick: Mapped["DailyPick"] = relationship(back_populates="comments")
