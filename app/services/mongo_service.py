from __future__ import annotations

from functools import lru_cache

from pymongo import MongoClient

from app.config import get_settings


@lru_cache
def get_mongo_database():
    settings = get_settings()
    client = MongoClient(settings.mongodb_url, serverSelectionTimeoutMS=3000)
    client.admin.command("ping")
    database = client[settings.mongodb_database]
    database.users.create_index("username", unique=True)
    database.users.create_index("email", unique=True)
    database.alerts.create_index("alert_id", unique=True)
    database.alerts.create_index([("camera_id", 1), ("timestamp", -1)])
    database.alerts.create_index("timestamp")
    return database