from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.database import SessionLocal
from app.models import AlertRecord, CameraRecord, CameraStatus
from app.services.mongo_service import get_mongo_database


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

    def remove_camera(self, camera_id: str) -> list[str]:
        try:
            get_mongo_database().alerts.delete_many({"camera_id": camera_id})
        except Exception:
            pass
        alerts = self.session.query(AlertRecord).filter(AlertRecord.camera_id == camera_id).all()
        image_paths = [alert.image_path for alert in alerts if alert.image_path]
        for alert in alerts:
            self.session.delete(alert)
        record = self.session.query(CameraRecord).filter(CameraRecord.id == camera_id).first()
        if record:
            self.session.delete(record)
        self.session.commit()
        return image_paths

    def set_camera_alert(self, camera_id: str, alert_level: int, status: CameraStatus) -> None:
        record = self.session.query(CameraRecord).filter(CameraRecord.id == camera_id).first()
        if record:
            record.alert_level = alert_level
            record.status = status.value
            record.last_seen = datetime.now(timezone.utc)
            self.session.commit()

    def add_alert(self, alert_id: str, camera_id: str, camera_name: str, threat_type: str, severity: int, message: str, image_path: str | None, camera_location: str | None = None) -> AlertRecord:
        if not camera_location:
            camera = self.session.query(CameraRecord).filter(CameraRecord.id == camera_id).first()
            camera_location = camera.location if camera else "Unknown location"
        alert = AlertRecord(
            id=alert_id,
            camera_id=camera_id,
            camera_name=camera_name,
            camera_location=camera_location,
            threat_type=threat_type,
            severity=severity,
            message=message,
            timestamp=datetime.now(timezone.utc),
            image_path=image_path,
        )
        try:
            get_mongo_database().alerts.insert_one({
                "alert_id": alert_id,
                "camera_id": camera_id,
                "camera_name": camera_name,
                "camera_location": camera_location,
                "threat_type": threat_type,
                "severity": severity,
                "message": message,
                "timestamp": alert.timestamp,
                "image_path": image_path,
            })
        except Exception:
            pass
        self.session.add(alert)
        self.session.commit()
        self.session.refresh(alert)
        return alert

    def list_alerts(self) -> list[AlertRecord]:
        try:
            documents = list(get_mongo_database().alerts.find().sort("timestamp", -1))
            return [self._mongo_alert_to_record(document) for document in documents]
        except Exception:
            return self.session.query(AlertRecord).order_by(AlertRecord.timestamp.desc()).all()

    def list_alerts_between(self, start_at: datetime, end_at: datetime) -> list[AlertRecord]:
        try:
            documents = list(
                get_mongo_database().alerts.find({
                    "timestamp": {"$gte": start_at, "$lt": end_at},
                }).sort("timestamp", 1)
            )
            return [self._mongo_alert_to_record(document) for document in documents]
        except Exception:
            return (
                self.session.query(AlertRecord)
                .filter(AlertRecord.timestamp >= start_at, AlertRecord.timestamp < end_at)
                .order_by(AlertRecord.timestamp.asc())
                .all()
            )

    @staticmethod
    def _mongo_alert_to_record(document: dict) -> AlertRecord:
        return AlertRecord(
            id=document["alert_id"],
            camera_id=document["camera_id"],
            camera_name=document["camera_name"],
            camera_location=document.get("camera_location") or "Unknown location",
            threat_type=document["threat_type"],
            severity=document.get("severity", 1),
            message=document["message"],
            timestamp=document["timestamp"],
            image_path=document.get("image_path"),
        )
