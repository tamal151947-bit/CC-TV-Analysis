from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from app.models import AlertEvent, DetectionResult, ThreatType


class DetectionService:
    def __init__(self, camera_registry) -> None:
        self.camera_registry = camera_registry

    def detect(self, camera_id: str, threat_type: ThreatType, confidence: float = 0.9, image_path: str | None = None) -> DetectionResult:
        camera = self.camera_registry.get_camera(camera_id)
        if not camera:
            raise ValueError(f"Camera {camera_id} not found")

        message = self._build_message(threat_type, camera.name)
        result = DetectionResult(
            camera_id=camera_id,
            threat_type=threat_type,
            confidence=confidence,
            message=message,
            image_path=image_path,
        )
        self.camera_registry.set_alert(camera_id, alert_level=max(1, int(confidence * 5)))
        return result

    def _build_message(self, threat_type: ThreatType, camera_name: str) -> str:
        mapping = {
            ThreatType.THEFT: f"Theft or suspicious theft activity detected on {camera_name}.",
            ThreatType.INTRUSION: f"Home intrusion detected on {camera_name}.",
            ThreatType.VIOLENCE: f"Violence or fight activity detected on {camera_name}.",
            ThreatType.MISSING_OBJECT: f"Missing object alert triggered on {camera_name}.",
            ThreatType.SUSPICIOUS_ACTIVITY: f"Suspicious activity detected on {camera_name}.",
        }
        return mapping.get(threat_type, f"Unusual activity detected on {camera_name}.")

    def create_alert_event(self, detection: DetectionResult) -> AlertEvent:
        camera = self.camera_registry.get_camera(detection.camera_id)
        return AlertEvent(
            id=f"alert-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
            camera_id=detection.camera_id,
            camera_name=camera.name if camera else "Unknown Camera",
            threat_type=detection.threat_type,
            severity=max(1, int(detection.confidence * 10)),
            message=detection.message,
            timestamp=datetime.now(timezone.utc),
            image_path=detection.image_path,
        )

    def get_simulation_options(self) -> List[str]:
        return [
            ThreatType.THEFT.value,
            ThreatType.INTRUSION.value,
            ThreatType.VIOLENCE.value,
            ThreatType.MISSING_OBJECT.value,
            ThreatType.SUSPICIOUS_ACTIVITY.value,
        ]
