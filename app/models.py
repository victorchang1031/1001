import datetime
from sqlalchemy import ForeignKey, String, Integer, Date, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class User(Base):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )


class Album(Base):
    __tablename__ = "album"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String)
    artist: Mapped[str] = mapped_column(String)
    year: Mapped[int] = mapped_column(Integer)
    genre: Mapped[str | None] = mapped_column(String, nullable=True)
    spotify_url: Mapped[str | None] = mapped_column(String, nullable=True)
    wikipedia_url: Mapped[str | None] = mapped_column(String, nullable=True)
    cover_image_url: Mapped[str | None] = mapped_column(String, nullable=True)


class Server(Base):
    __tablename__ = "server"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )


class Membership(Base):
    __tablename__ = "membership"
    __table_args__ = (UniqueConstraint("user_id", "server_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    server_id: Mapped[int] = mapped_column(ForeignKey("server.id"))
    joined_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )


class DailyPick(Base):
    __tablename__ = "daily_pick"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    server_id: Mapped[int | None] = mapped_column(ForeignKey("server.id"), nullable=True)
    date: Mapped[datetime.date] = mapped_column(Date)
    album_id: Mapped[int] = mapped_column(ForeignKey("album.id"))
    status: Mapped[str] = mapped_column(String, default="pending")
    revealed_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    album: Mapped["Album"] = relationship()
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="daily_pick", cascade="all, delete-orphan"
    )


class DrawHistory(Base):
    __tablename__ = "draw_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    server_id: Mapped[int | None] = mapped_column(ForeignKey("server.id"), nullable=True)
    album_id: Mapped[int] = mapped_column(ForeignKey("album.id"))
    drawn_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    album: Mapped["Album"] = relationship()


class Comment(Base):
    __tablename__ = "comment"
    id: Mapped[int] = mapped_column(primary_key=True)
    daily_pick_id: Mapped[int] = mapped_column(ForeignKey("daily_pick.id"))
    content: Mapped[str] = mapped_column(String)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    daily_pick: Mapped["DailyPick"] = relationship(back_populates="comments")
