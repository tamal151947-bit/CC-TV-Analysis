from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt
from passlib.context import CryptContext
from app.config import get_settings
from app.database import SessionLocal
from app.models import UserRecord
from app.services.mongo_service import get_mongo_database

settings = get_settings()
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_token(username: str, session_id: str | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=8)
    payload = {"sub": username, "exp": expire, "session_id": session_id}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def get_user_by_username(username: str) -> Optional[dict[str, Any]]:
    try:
        mongo_user = get_mongo_database().users.find_one({"username": username})
        if mongo_user:
            return mongo_user
    except Exception:
        pass

    db = SessionLocal()
    try:
        user = db.query(UserRecord).filter(UserRecord.username == username).first()
        if not user:
            return None
        return {
            "username": user.username,
            "name": user.username,
            "email": settings.admin_email,
            "password_hash": user.password_hash,
            "is_verified": True,
            "role": user.role,
        }
    finally:
        db.close()


def ensure_default_admin() -> None:
    db = SessionLocal()
    try:
        user = db.query(UserRecord).filter(UserRecord.username == settings.default_admin_username).first()
        if user is None:
            db.add(UserRecord(
                username=settings.default_admin_username,
                password_hash=hash_password(settings.default_admin_password),
                role="admin",
            ))
            db.commit()
    finally:
        db.close()

    try:
        get_mongo_database().users.update_one(
            {"username": settings.default_admin_username},
            {
                "$setOnInsert": {
                    "username": settings.default_admin_username,
                    "name": "Administrator",
                    "email": settings.admin_email,
                    "password_hash": hash_password(settings.default_admin_password),
                    "is_verified": True,
                    "role": "admin",
                    "created_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )
    except Exception:
        pass


def authenticate_user(username: str, password: str) -> Optional[dict[str, Any]]:
    user = get_user_by_username(username)
    if user and user.get("is_verified") and verify_password(password, user["password_hash"]):
        return user
    return None


def authenticate_mongo_user(username: str, password: str) -> bool:
    user = get_mongo_database().users.find_one({"username": username})
    return bool(user and user.get("is_verified") and verify_password(password, user["password_hash"]))


def create_pending_user(name: str, username: str, email: str, password: str) -> str:
    database = get_mongo_database()
    if database.users.find_one({"$or": [{"username": username}, {"email": email}]}) is not None:
        raise ValueError("Username or email is already registered")

    code = f"{secrets.randbelow(1_000_000):06d}"
    database.users.insert_one(
        {
            "name": name,
            "username": username,
            "email": email,
            "password_hash": hash_password(password),
            "is_verified": False,
            "verification_code_hash": hash_password(code),
            "verification_expires_at": datetime.now(timezone.utc) + timedelta(minutes=15),
            "role": "user",
            "created_at": datetime.now(timezone.utc),
        }
    )
    return code


def delete_pending_user(username: str) -> None:
    get_mongo_database().users.delete_one({"username": username, "is_verified": False})


def verify_user_code(email: str, code: str) -> bool:
    user = get_mongo_database().users.find_one({"email": email})
    expires_at = user.get("verification_expires_at") if user else None
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if not user or user.get("is_verified") or not expires_at or datetime.now(timezone.utc) > expires_at:
        return False
    if not verify_password(code, user.get("verification_code_hash", "")):
        return False
    get_mongo_database().users.update_one(
        {"_id": user["_id"]},
        {"$set": {"is_verified": True}, "$unset": {"verification_code_hash": "", "verification_expires_at": ""}},
    )
    return True


def create_password_reset_code(email: str) -> str | None:
    database = get_mongo_database()
    user = database.users.find_one({"email": email, "is_verified": True})
    if not user:
        return None
    code = f"{secrets.randbelow(1_000_000):06d}"
    database.users.update_one(
        {"_id": user["_id"]},
        {"$set": {
            "reset_code_hash": hash_password(code),
            "reset_expires_at": datetime.now(timezone.utc) + timedelta(minutes=15),
        }},
    )
    return code


def get_verified_user_by_email(email: str) -> dict[str, Any] | None:
    return get_mongo_database().users.find_one({"email": email, "is_verified": True})


def reset_password(email: str, code: str, password: str) -> bool:
    database = get_mongo_database()
    user = database.users.find_one({"email": email, "is_verified": True})
    expires_at = user.get("reset_expires_at") if user else None
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if not user or not expires_at or datetime.now(timezone.utc) > expires_at:
        return False
    if not verify_password(code, user.get("reset_code_hash", "")):
        return False
    database.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"password_hash": hash_password(password)}, "$unset": {"reset_code_hash": "", "reset_expires_at": ""}},
    )
    return True


def update_user(username: str, name: str, email: str, password: str | None = None) -> dict[str, Any]:
    database = get_mongo_database()
    duplicate = database.users.find_one({"email": email, "username": {"$ne": username}})
    if duplicate:
        raise ValueError("That email is already in use")
    updates: dict[str, Any] = {"name": name, "email": email}
    if password:
        updates["password_hash"] = hash_password(password)
    database.users.update_one({"username": username}, {"$set": updates})
    return database.users.find_one({"username": username})
