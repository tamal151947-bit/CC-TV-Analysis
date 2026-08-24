from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import uuid

from app.config import get_settings
from app.services.email_service import EmailAlertService
from app.services.mongo_service import get_mongo_database

settings = get_settings()

SUBSCRIPTION_PLANS: dict[str, dict[str, Any]] = {
    "free": {
        "code": "free",
        "name": "Free",
        "max_cameras": 2,
        "price_inr": 0,
        "validity_days": 30,
        "description": "Basic monitoring for up to 2 cameras.",
        "features": [
            "2 Cameras",
            "Live Monitoring",
            "AI Smart Alerts",
            "Real-time Incident Picture Sent to Email",
            "30-Day Access",
            "Basic AI Detection",
        ],
    },
    "silver": {
        "code": "silver",
        "name": "Silver",
        "max_cameras": 5,
        "price_inr": 1,
        "validity_days": 30,
        "description": "Perfect for small business monitoring across 3 to 5 cameras.",
        "features": [
            "5 Cameras",
            "Live Monitoring",
            "AI Smart Alerts",
            "Real-time Incident Picture Sent to Email",
            "30-Day Access",
            "Faster Alert Notifications",
            "Multi-Camera Monitoring",
        ],
    },
    "gold": {
        "code": "gold",
        "name": "Gold",
        "max_cameras": 10,
        "price_inr": 299,
        "validity_days": 30,
        "description": "Ideal for growing security teams operating 6 to 10 cameras.",
        "features": [
            "10 Cameras",
            "Live Monitoring",
            "AI Smart Alerts",
            "Real-time Incident Picture Sent to Email",
            "24-Hour PDF Security Report",
            "30-Day Access",
            "Detailed AI Activity Summary",
            "Advanced Camera Monitoring",
        ],
    },
    "diamond": {
        "code": "diamond",
        "name": "Diamond",
        "max_cameras": 20,
        "price_inr": 499,
        "validity_days": 30,
        "description": "Built for large deployments with 11 to 20 cameras and advanced coverage.",
        "features": [
            "20 Cameras",
            "Live Monitoring",
            "AI Smart Alerts",
            "Real-time Incident Picture Sent to Email",
            "24-Hour PDF Security Report",
            "Detailed AI Activity Summary",
            "Priority Security Alerts",
            "Advanced Multi-Camera Monitoring",
            "Complete Daily Security Overview",
            "All-in-One AI Protection",
        ],
    },
}

PLAN_ORDER = ["free", "silver", "gold", "diamond"]


def list_subscription_plans() -> list[dict[str, Any]]:
    return [SUBSCRIPTION_PLANS[plan_code] for plan_code in PLAN_ORDER]


def get_plan_for_camera_count(camera_count: int) -> dict[str, Any]:
    count = max(0, int(camera_count))
    if count <= 2:
        return SUBSCRIPTION_PLANS["free"]
    if count <= 5:
        return SUBSCRIPTION_PLANS["silver"]
    if count <= 10:
        return SUBSCRIPTION_PLANS["gold"]
    return SUBSCRIPTION_PLANS["diamond"]


def _normalize_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def user_subscription_defaults() -> dict[str, Any]:
    return {
        "plan_code": "free",
        "plan_name": "Free",
        "price_inr": 0,
        "max_cameras": 2,
        "validity_days": 30,
        "expires_at": None,
        "auto_renew": False,
        "status": "active",
        "payment_method": "UPI",
        "last_paid_at": None,
        "renewal_reminder_sent_at": None,
    }


def get_user_subscription(username: str) -> dict[str, Any]:
    database = get_mongo_database()
    user = database.users.find_one({"username": username})
    if not user:
        return user_subscription_defaults()

    subscription = user.get("subscription") or {}
    default = user_subscription_defaults()
    default.update(subscription)

    plan = SUBSCRIPTION_PLANS.get(default.get("plan_code"), SUBSCRIPTION_PLANS["free"])
    default["plan_code"] = plan["code"]
    default["plan_name"] = plan["name"]
    default["price_inr"] = plan["price_inr"]
    default["max_cameras"] = plan["max_cameras"]
    default["validity_days"] = plan["validity_days"]
    default["auto_renew"] = bool(default.get("auto_renew"))
    default["status"] = "active"

    expires_at = _normalize_datetime(default.get("expires_at"))
    if expires_at and expires_at <= datetime.now(timezone.utc):
        default["status"] = "expired"
        default["plan_code"] = "free"
        default["plan_name"] = "Free"
        default["price_inr"] = 0
        default["max_cameras"] = 2
        default["validity_days"] = 30
    elif expires_at:
        default["status"] = "active"

    if expires_at and expires_at > datetime.now(timezone.utc):
        default["days_remaining"] = max(0, (expires_at - datetime.now(timezone.utc)).days)
    else:
        default["days_remaining"] = 0

    return default


def update_user_subscription(username: str, plan_code: str, auto_renew: bool = False, payment_method: str = "UPI") -> dict[str, Any]:
    plan = SUBSCRIPTION_PLANS.get(plan_code, SUBSCRIPTION_PLANS["free"])
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=plan["validity_days"])

    subscription = {
        "plan_code": plan["code"],
        "plan_name": plan["name"],
        "price_inr": plan["price_inr"],
        "max_cameras": plan["max_cameras"],
        "validity_days": plan["validity_days"],
        "expires_at": expires_at.isoformat(),
        "auto_renew": bool(auto_renew),
        "payment_method": payment_method,
        "last_paid_at": now.isoformat(),
        "status": "active",
        "renewal_reminder_sent_at": None,
    }

    database = get_mongo_database()
    database.users.update_one({"username": username}, {"$set": {"subscription": subscription}}, upsert=True)
    return subscription


def process_subscription_payment(username: str, plan_code: str, auto_renew: bool = False, payment_method: str = "UPI") -> dict[str, Any]:
    if plan_code not in SUBSCRIPTION_PLANS:
        raise ValueError("Invalid subscription plan selected.")

    plan = SUBSCRIPTION_PLANS[plan_code]
    gateway_reference = f"PAY-{uuid.uuid4().hex[:12]}"
    charge_amount = int(plan["price_inr"])

    subscription = update_user_subscription(username, plan_code, auto_renew=auto_renew, payment_method=payment_method)
    result = {
        "status": "paid",
        "customer": username,
        "plan_code": plan["code"],
        "plan_name": plan["name"],
        "amount_paid_inr": charge_amount,
        "payment_method": payment_method,
        "auto_renew": bool(auto_renew),
        "gateway_reference": gateway_reference,
        "expires_at": subscription["expires_at"],
        "expires_in_days": plan["validity_days"],
        "message": f"Subscription activated for {plan['name']}.",
    }
    if settings.payment_gateway_provider and settings.payment_gateway_provider != "demo":
        result["gateway_mode"] = settings.payment_gateway_provider
    else:
        result["gateway_mode"] = "demo"
    return result


def toggle_auto_renew(username: str, enabled: bool) -> dict[str, Any]:
    database = get_mongo_database()
    user = database.users.find_one({"username": username})
    if not user:
        raise ValueError("User not found")
    subscription = user.get("subscription") or user_subscription_defaults()
    subscription["auto_renew"] = bool(enabled)
    database.users.update_one({"username": username}, {"$set": {"subscription": subscription}})
    return subscription


def get_subscription_status(username: str) -> dict[str, Any]:
    subscription = get_user_subscription(username)
    if subscription["status"] == "expired" and subscription.get("auto_renew"):
        return process_subscription_payment(username, subscription.get("plan_code", "free"), auto_renew=True, payment_method=subscription.get("payment_method", "UPI"))
    return {
        "status": subscription["status"],
        "plan_code": subscription["plan_code"],
        "expires_at": subscription.get("expires_at"),
        "days_remaining": subscription.get("days_remaining", 0),
        "auto_renew": subscription.get("auto_renew", False),
    }


def send_subscription_renewal_reminder(username: str) -> bool:
    user = get_mongo_database().users.find_one({"username": username})
    if not user:
        return False
    email_address = user.get("email")
    if not email_address:
        return False
    subscription = get_user_subscription(username)
    if subscription["status"] == "active":
        return False

    email_service = EmailAlertService(
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        username=settings.smtp_user,
        password=settings.smtp_password,
        to_address=settings.alert_email_to,
    )
    if not email_service.send_subscription_reminder(email_address, subscription["plan_name"], subscription.get("expires_at")):
        return False
    return True


def check_and_send_expiring_soon_reminders() -> list[str]:
    database = get_mongo_database()
    users = list(database.users.find({}))
    recipients: list[str] = []
    now = datetime.now(timezone.utc)
    email_service = EmailAlertService(
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        username=settings.smtp_user,
        password=settings.smtp_password,
        to_address=settings.alert_email_to,
    )

    for user in users:
        subscription = user.get("subscription") or user_subscription_defaults()
        expires_at = _normalize_datetime(subscription.get("expires_at"))
        if not expires_at:
            continue
        remaining_days = (expires_at - now).total_seconds() / 86400
        if 2 <= remaining_days <= 3 and not subscription.get("renewal_reminder_sent_at"):
            email = user.get("email")
            if email and email_service.send_subscription_reminder(email, subscription.get("plan_name", "plan"), expires_at.isoformat()):
                subscription["renewal_reminder_sent_at"] = now.isoformat()
                database.users.update_one({"username": user["username"]}, {"$set": {"subscription": subscription}})
                recipients.append(user["username"])
    return recipients


def validate_camera_limit(username: str | None, camera_count: int) -> dict[str, Any]:
    if username is None:
        return {"allowed": True, "plan": SUBSCRIPTION_PLANS["free"], "camera_count": camera_count}

    subscription = get_user_subscription(username)
    plan = SUBSCRIPTION_PLANS.get(subscription["plan_code"], SUBSCRIPTION_PLANS["free"])
    limit = plan["max_cameras"]
    if camera_count > limit:
        return {
            "allowed": False,
            "plan": plan,
            "camera_count": camera_count,
            "message": f"You have reached the {plan['name']} limit of {limit} cameras. Upgrade to continue adding cameras.",
        }
    return {"allowed": True, "plan": plan, "camera_count": camera_count}
