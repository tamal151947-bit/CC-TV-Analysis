from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import declarative_base
from pydantic import BaseModel, Field

Base = declarative_base()


class ThreatType(str, Enum):
    THEFT = "theft"
    INTRUSION = "intrusion"
    VIOLENCE = "violence"
    MISSING_OBJECT = "missing_object"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"


class CameraStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    ALERT = "alert"


class Camera(BaseModel):
    id: str
    name: str
    location: str
    rtsp_url: str
    status: CameraStatus = CameraStatus.ONLINE
    alert_level: int = 0
    last_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AlertEvent(BaseModel):
    id: str
    camera_id: str
    camera_name: str
    threat_type: ThreatType
    severity: int = Field(default=1)
    message: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    image_path: Optional[str] = None


class DetectionResult(BaseModel):
    camera_id: str
    threat_type: ThreatType
    confidence: float
    message: str
    image_path: Optional[str] = None


class CameraRecord(Base):
    __tablename__ = "camera_records"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    location = Column(String, nullable=False)
    rtsp_url = Column(String, nullable=False)
    status = Column(String, default=CameraStatus.ONLINE.value)
    alert_level = Column(Integer, default=0)
    last_seen = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class UserRecord(Base):
    __tablename__ = "user_records"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="admin")


class AlertRecord(Base):
    __tablename__ = "alert_records"

    id = Column(String, primary_key=True, index=True)
    camera_id = Column(String, nullable=False)
    camera_name = Column(String, nullable=False)
    threat_type = Column(String, nullable=False)
    severity = Column(Integer, default=1)
    message = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    image_path = Column(String, nullable=True)
