from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "CCTV AI Guard"
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True
    admin_email: str = "admin@example.com"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = "your-gmail@gmail.com"
    smtp_password: str = "your-app-password"
    alert_email_to: str = "admin@example.com"
    database_url: str = "sqlite:///./cctv_guard.db"
    mongodb_url: str = "mongodb://localhost:27017"
    mongodb_database: str = "cctv_guard"
    secret_key: str = "change-this-secret-key"
    yolo_model_path: str = "yolov8n.pt"
    frame_store_dir: str = "./captured_frames"
    default_admin_username: str = "admin"
    default_admin_password: str = "admin123"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
