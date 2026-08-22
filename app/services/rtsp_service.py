from __future__ import annotations

import os
import time
from typing import Any

import cv2


class RTSPStreamManager:
    def __init__(self, store_dir: str) -> None:
        self.store_dir = store_dir
        os.makedirs(self.store_dir, exist_ok=True)

    def open_stream(self, rtsp_url: str):
        source = int(rtsp_url.removeprefix("webcam://")) if rtsp_url.startswith("webcam://") else rtsp_url
        return cv2.VideoCapture(source)

    def capture_frame(self, rtsp_url: str, output_path: str | None = None) -> str | None:
        cap = self.open_stream(rtsp_url)
        if not cap.isOpened():
            return None

        try:
            ret, frame = cap.read()
            if not ret or frame is None:
                return None

            if output_path is None:
                file_name = f"frame_{int(time.time() * 1000)}.jpg"
                output_path = os.path.join(self.store_dir, file_name)

            cv2.imwrite(output_path, frame)
            return output_path
        finally:
            cap.release()

    def get_latest_frame(self, rtsp_url: str) -> Any | None:
        cap = self.open_stream(rtsp_url)
        if not cap.isOpened():
            return None

        try:
            ret, frame = cap.read()
            if not ret or frame is None:
                return None
            return frame
        finally:
            cap.release()
