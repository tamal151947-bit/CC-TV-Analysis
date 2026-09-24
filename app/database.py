from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models import Base

settings = get_settings()
engine = create_engine(settings.database_url, connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _migrate_alert_records()
    from app.services.auth_service import ensure_default_admin

    ensure_default_admin()


def _migrate_alert_records() -> None:
    if engine.dialect.name != "sqlite":
        return
    columns = {column["name"] for column in inspect(engine).get_columns("alert_records")}
    if "camera_location" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE alert_records ADD COLUMN camera_location VARCHAR NOT NULL DEFAULT 'Unknown location'"))
