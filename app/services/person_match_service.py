from __future__ import annotations

import cv2
import numpy as np


class PersonMatchService:
    """Keeps a local reference image and compares it with live camera frames."""

    def __init__(self) -> None:
        self.reference_name: str | None = None
        self.reference_paths: list[str] = []
        self.reference_descriptors: list[np.ndarray] = []
        self.detector = cv2.SIFT_create()
        self.matcher = cv2.BFMatcher()
        self.face_detector = None
        if hasattr(cv2, "CascadeClassifier") and hasattr(cv2, "data"):
            self.face_detector = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            )

    def set_reference(self, name: str, image_path: str) -> None:
        self.set_references(name, [image_path])

    def set_references(self, name: str, image_paths: list[str]) -> None:
        descriptors_list = []
        usable_paths = []
        for image_path in image_paths:
            image = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
            if image is None:
                continue
            image = self._face_or_image(image)
            _, descriptors = self.detector.detectAndCompute(image, None)
            if descriptors is not None and len(descriptors) >= 2:
                descriptors_list.append(descriptors)
                usable_paths.append(image_path)
        if not usable_paths:
            raise ValueError("None of the uploaded pictures could be read. Use clear JPG or PNG images.")
        self.reference_name = name.strip() or "Tracked person"
        self.reference_paths = usable_paths
        self.reference_descriptors = descriptors_list

    def clear_reference(self) -> None:
        self.reference_name = None
        self.reference_paths = []
        self.reference_descriptors = []

    def is_configured(self) -> bool:
        return bool(self.reference_descriptors)

    def matches(self, frame: object) -> bool:
        if not self.reference_descriptors or not isinstance(frame, np.ndarray):
            return False
        candidates = [frame]
        return any(self._matches_image(candidate) for candidate in candidates)

    def matches_person_crops(self, crops: list[object]) -> bool:
        return any(self._matches_image(crop) for crop in crops)

    def _matches_image(self, image: object) -> bool:
        if not isinstance(image, np.ndarray) or image.size == 0:
            return False
        image = self._face_or_image(image)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, descriptors = self.detector.detectAndCompute(gray, None)
        if descriptors is None or len(descriptors) < 2:
            return False
        for reference_descriptors in self.reference_descriptors:
            pairs = self.matcher.knnMatch(reference_descriptors, descriptors, k=2)
            good_matches = [first for first, second in pairs if first.distance < 0.78 * second.distance]
            if len(good_matches) >= max(4, min(12, len(reference_descriptors) // 10)):
                return True
        return False

    def _face_or_image(self, image: np.ndarray) -> np.ndarray:
        gray = image if len(image.shape) == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if self.face_detector is None:
            return image[: max(1, int(image.shape[0] * 0.7)), :]
        faces = self.face_detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(40, 40))
        if len(faces) == 0:
            return image
        x, y, width, height = max(faces, key=lambda face: face[2] * face[3])
        padding_x = int(width * 0.2)
        padding_y = int(height * 0.25)
        top = max(0, y - padding_y)
        bottom = min(image.shape[0], y + height + padding_y)
        left = max(0, x - padding_x)
        right = min(image.shape[1], x + width + padding_x)
        return image[top:bottom, left:right]