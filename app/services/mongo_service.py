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
    return database