from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

from app.models import Camera, CameraStatus


class CameraRegistry:
    def __init__(self) -> None:
        self.cameras: Dict[str, Camera] = {}

    def _seed_demo_cameras(self) -> None:
        for idx in range(1, 11):
            camera = Camera(
                id=f"cam-{idx:02d}",
                name=f"CCTV Camera {idx}",
                location=f"Zone {idx}",
                rtsp_url=f"rtsp://camera.example/{idx}",
                status=CameraStatus.OFFLINE,
                last_seen=datetime.now(timezone.utc),
            )
            self.cameras[camera.id] = camera

    def list_cameras(self) -> List[Camera]:
        return list(self.cameras.values())

    def get_camera(self, camera_id: str) -> Camera | None:
        return self.cameras.get(camera_id)

    def set_alert(self, camera_id: str, alert_level: int = 1) -> Camera | None:
        camera = self.cameras.get(camera_id)
        if not camera:
            return None
        camera.alert_level = alert_level
        camera.status = CameraStatus.ALERT
        camera.last_seen = datetime.now(timezone.utc)
        return camera

    def clear_alert(self, camera_id: str) -> Camera | None:
        camera = self.cameras.get(camera_id)
        if not camera:
            return None
        camera.alert_level = 0
        camera.status = CameraStatus.ONLINE
        camera.last_seen = datetime.now(timezone.utc)
        return camera
