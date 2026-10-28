"""Pydantic request/response models mirroring PRD 7.3."""
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from .engine.acoustic import parse_camelot


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    displayName: str = Field(min_length=2, max_length=40, pattern=r"^[\w .'-]+$")


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    refreshToken: str


class LoungeCreateIn(BaseModel):
    seedTrackId: str
    vibeProfile: str = Field(min_length=2, max_length=64)
    maxParticipants: int = Field(50, ge=2, le=50)
    bpmTolerancePct: float = Field(8, gt=0, le=8)
    soundclashEnabled: bool = True
    aiVerbosity: Literal["minimal", "normal", "chatty"] = "normal"


class SegueIn(BaseModel):
    currentTrackId: str
    currentTs: float = 0
    candidateTrackIds: list[str] = Field(min_length=1, max_length=50)
    currentSentimentScore: float = Field(0.5, ge=0, le=1)
    apply: bool = False


class AcousticIn(BaseModel):
    bpm: float = Field(gt=0, le=300, description="Beats per minute, positive")
    camelotKey: str
    energy: float = Field(ge=0, le=1)
    valence: float = Field(ge=0, le=1)

    @field_validator("camelotKey")
    @classmethod
    def valid_key(cls, v: str) -> str:
        n, letter = parse_camelot(v)  # raises ValueError with a clear message
        return f"{n}{letter}"


class TimelineIn(BaseModel):
    ts: int = Field(ge=0)
    type: Literal["sample_credit", "trivia", "glossary", "artist_bio"]
    text: str = Field(min_length=3, max_length=400)


class TrackUploadIn(BaseModel):
    trackId: str | None = Field(None, pattern=r"^t_[A-Za-z0-9_]{1,28}$")
    title: str = Field(min_length=1, max_length=200)
    artist: str = Field(min_length=1, max_length=200)
    durationSeconds: int = Field(gt=10, le=1800)
    audioAssetUrl: str | None = Field(None, max_length=500)
    acoustic: AcousticIn
    timeline: list[TimelineIn] = Field(default_factory=list, max_length=50)
