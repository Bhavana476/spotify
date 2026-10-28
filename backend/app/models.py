"""Relational schema (PRD 7.2.2). Live queue state is held in memory; these tables are the durable record."""
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String,
                        Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

ROLES = ("listener", "co_dj", "host", "admin")


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="listener")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (CheckConstraint("role in ('listener','co_dj','host','admin')", name="ck_user_role"),)


class Track(Base):
    __tablename__ = "tracks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    artist: Mapped[str] = mapped_column(String(200))
    duration_seconds: Mapped[int] = mapped_column(Integer)
    audio_asset_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bpm: Mapped[float] = mapped_column(Float, index=True)
    camelot_key: Mapped[str] = mapped_column(String(3), index=True)
    energy: Mapped[float] = mapped_column(Float, index=True)
    valence: Mapped[float] = mapped_column(Float)
    __table_args__ = (
        CheckConstraint("bpm > 0", name="ck_track_bpm"),
        CheckConstraint("energy >= 0 and energy <= 1", name="ck_track_energy"),
        CheckConstraint("valence >= 0 and valence <= 1", name="ck_track_valence"),
    )


class TrackTimelineEvent(Base):
    __tablename__ = "track_timeline_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    track_id: Mapped[str] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"), index=True)
    ts_seconds: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON)  # {"text": "..."}
    __table_args__ = (CheckConstraint("event_type in ('sample_credit','trivia','glossary','artist_bio')",
                                      name="ck_timeline_type"),)


class Lounge(Base):
    __tablename__ = "dj_lounges"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    invite_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    host_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    vibe_profile: Mapped[str] = mapped_column(String(64))
    seed_track_id: Mapped[str] = mapped_column(ForeignKey("tracks.id"))
    current_track_id: Mapped[str | None] = mapped_column(ForeignKey("tracks.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="scheduled")
    max_participants: Mapped[int] = mapped_column(Integer, default=50)
    bpm_tolerance_pct: Mapped[float] = mapped_column(Float, default=8)
    soundclash_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    ai_verbosity: Mapped[str] = mapped_column(String(16), default="normal")
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # written once when the lounge ends
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (CheckConstraint("status in ('scheduled','live','ended')", name="ck_lounge_status"),)


class QueueEntry(Base):
    """Snapshot of the queue, written when the lounge ends or the host checkpoints it. Sparse positions."""
    __tablename__ = "queue_entries"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    lounge_id: Mapped[str] = mapped_column(ForeignKey("dj_lounges.id", ondelete="CASCADE"), index=True)
    track_id: Mapped[str] = mapped_column(ForeignKey("tracks.id"))
    position: Mapped[int] = mapped_column(Integer)
    vote_count: Mapped[int] = mapped_column(Integer, default=0)
    added_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    __table_args__ = (Index("ix_queue_lounge_pos", "lounge_id", "position"),)


class SoundclashBattle(Base):
    __tablename__ = "soundclash_battles"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    lounge_id: Mapped[str] = mapped_column(ForeignKey("dj_lounges.id", ondelete="CASCADE"), index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="open")
    winning_track_id: Mapped[str | None] = mapped_column(ForeignKey("tracks.id"), nullable=True)


class SoundclashCandidate(Base):
    __tablename__ = "soundclash_candidates"
    id: Mapped[int] = mapped_column(primary_key=True)
    battle_id: Mapped[str] = mapped_column(ForeignKey("soundclash_battles.id", ondelete="CASCADE"), index=True)
    track_id: Mapped[str] = mapped_column(ForeignKey("tracks.id"))
    submitted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    vote_count: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("battle_id", "track_id"),)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    lounge_id: Mapped[str] = mapped_column(ForeignKey("dj_lounges.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    msg_type: Mapped[str] = mapped_column(String(24))
    body: Mapped[str] = mapped_column(Text)
    sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ts_seconds: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (CheckConstraint("msg_type in ('chat','ai_answer','system','dj_announcement')",
                                      name="ck_chat_type"),)


class QueueEvent(Base):
    """Append-only event log: votes, segues, battles, presence, sentiment ticks. Analytics derive from this."""
    __tablename__ = "queue_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    lounge_id: Mapped[str] = mapped_column(ForeignKey("dj_lounges.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    ts: Mapped[float] = mapped_column(Float)  # epoch seconds
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Interaction(Base):
    __tablename__ = "interactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    track_id: Mapped[str] = mapped_column(ForeignKey("tracks.id"), index=True)
    lounge_id: Mapped[str | None] = mapped_column(ForeignKey("dj_lounges.id"), nullable=True)
    played_seconds: Mapped[float] = mapped_column(Float, default=0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    liked: Mapped[bool] = mapped_column(Boolean, default=False)
    co_listened_with: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
