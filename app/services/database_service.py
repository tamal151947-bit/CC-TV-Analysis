from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.database import SessionLocal
from app.models import AlertRecord, CameraRecord, CameraStatus


class CameraDatabaseService:
    def __init__(self) -> None:
        self.session = SessionLocal()

    def add_or_update_camera(self, camera_id: str, name: str, location: str, rtsp_url: str) -> CameraRecord:
        record = self.session.query(CameraRecord).filter(CameraRecord.id == camera_id).first()
        if record is None:
            record = CameraRecord(id=camera_id, name=name, location=location, rtsp_url=rtsp_url)
            self.session.add(record)
        else:
            record.name = name
            record.location = location
            record.rtsp_url = rtsp_url
            record.last_seen = datetime.now(timezone.utc)
        self.session.commit()
        self.session.refresh(record)
        return record

    def list_cameras(self) -> list[CameraRecord]:
        return self.session.query(CameraRecord).all()

    def set_camera_alert(self, camera_id: str, alert_level: int, status: CameraStatus) -> None:
        record = self.session.query(CameraRecord).filter(CameraRecord.id == camera_id).first()
        if record:
            record.alert_level = alert_level
            record.status = status.value
            record.last_seen = datetime.now(timezone.utc)
            self.session.commit()

    def add_alert(self, alert_id: str, camera_id: str, camera_name: str, threat_type: str, severity: int, message: str, image_path: str | None) -> AlertRecord:
        alert = AlertRecord(
            id=alert_id,
            camera_id=camera_id,
            camera_name=camera_name,
            threat_type=threat_type,
            severity=severity,
            message=message,
            timestamp=datetime.now(timezone.utc),
            image_path=image_path,
        )
        self.session.add(alert)
        self.session.commit()
        self.session.refresh(alert)
        return alert

    def list_alerts(self) -> list[AlertRecord]:
        return self.session.query(AlertRecord).order_by(AlertRecord.timestamp.desc()).all()
