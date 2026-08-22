from __future__ import annotations

import os
from typing import Any, List, Tuple

import cv2

from app.config import get_settings

settings = get_settings()


class YOLODetectionService:
    def __init__(self, model_path: str | None = None) -> None:
        self.model_path = model_path or settings.yolo_model_path
        self.model = None
        self._load_model()

    def _load_model(self) -> None:
        try:
            from ultralytics import YOLO

            self.model = YOLO(self.model_path)
        except Exception:
            self.model = None

    def analyze_frame(self, frame: Any) -> Tuple[bool, List[dict], str | None]:
        if self.model is None:
            return False, [], None

        try:
            results = self.model(frame, verbose=False)[0]
            detections = []
            for box in results.boxes:
                cls = int(box.cls[0])
                conf = float(box.conf[0])
                label = self.model.names.get(cls, "object")
                detections.append({"label": label, "confidence": conf})

            suspicious = any(item["label"] in {"person", "car", "bottle", "knife"} for item in detections)
            return suspicious, detections, None
        except Exception:
            return False, [], None

    def save_debug_frame(self, frame: Any, path: str) -> str:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cv2.imwrite(path, frame)
        return path
