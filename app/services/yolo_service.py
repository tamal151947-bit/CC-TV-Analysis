from __future__ import annotations

import os
from typing import Any, List, Tuple

import cv2

from app.config import get_settings
from app.models import ThreatType

settings = get_settings()


class YOLODetectionService:
    def __init__(self, model_path: str | None = None) -> None:
        self.model_path = model_path or settings.yolo_model_path
        if not os.path.exists(self.model_path) and os.path.exists("yolov8n.pt"):
            self.model_path = "yolov8n.pt"
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

    def detect_threats(self, frame: Any) -> tuple[list[tuple[ThreatType, float]], List[dict]]:
        if self.model is None:
            return [], []

        try:
            results = self.model(frame, verbose=False)[0]
            detections = []
            threats: dict[ThreatType, float] = {}
            label_map = {
                "person": ThreatType.INTRUSION,
                "intruder": ThreatType.INTRUSION,
                "theft": ThreatType.THEFT,
                "stealing": ThreatType.THEFT,
                "robbery": ThreatType.THEFT,
                "fight": ThreatType.VIOLENCE,
                "violence": ThreatType.VIOLENCE,
                "harassment": ThreatType.VIOLENCE,
            }
            for box in results.boxes:
                cls = int(box.cls[0])
                confidence = float(box.conf[0])
                label = self.model.names.get(cls, "object").lower()
                detections.append({"label": label, "confidence": confidence})
                threat = label_map.get(label)
                if threat is not None:
                    threats[threat] = max(threats.get(threat, 0.0), confidence)
            return list(threats.items()), detections
        except Exception:
            return [], []

    def detect_person_crops(self, frame: Any) -> list[Any]:
        if self.model is None:
            return []
        try:
            result = self.model(frame, verbose=False, classes=[0], conf=0.35)[0]
            height, width = frame.shape[:2]
            crops = []
            for box in result.boxes.xyxy.int().cpu().tolist():
                left, top, right, bottom = box
                left = max(0, min(left, width - 1))
                top = max(0, min(top, height - 1))
                right = max(left + 1, min(right, width))
                bottom = max(top + 1, min(bottom, height))
                crop = frame[top:bottom, left:right]
                if crop.size:
                    crops.append(crop)
            return crops
        except Exception:
            return []

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
