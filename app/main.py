from __future__ import annotations

import os
import re
import secrets
import uuid
import asyncio
import threading
import time
import logging
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

import cv2
import numpy as np
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from pymongo.errors import PyMongoError

from app.config import get_settings
from app.database import init_db
from app.models import AlertEvent, Camera, CameraStatus, ThreatType
from app.services.alert_service import AlertManager
from app.services.alert_report_service import AlertReportService, date_range, utc_now
from app.services.auth_service import (
    authenticate_user,
    create_pending_user,
    create_token,
    create_password_reset_code,
    delete_pending_user,
    get_user_by_username,
    update_user,
    reset_password,
    get_verified_user_by_email,
    verify_user_code,
)
from app.services.camera_service import CameraRegistry
from app.services.database_service import CameraDatabaseService
from app.services.detection_service import DetectionService
from app.services.email_service import EmailAlertService
from app.services.person_match_service import PersonMatchService
from app.services.rtsp_service import RTSPStreamManager
from app.services.yolo_service import YOLODetectionService
from app.subscription_service import (
    check_and_send_expiring_soon_reminders,
    get_plan_for_camera_count,
    get_user_subscription,
    list_subscription_plans,
    process_subscription_payment,
    toggle_auto_renew,
    validate_camera_limit,
)

settings = get_settings()
init_db()
app_session_id = secrets.token_urlsafe(32)

app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

QR_IMAGE_PATH = Path(__file__).resolve().parent.parent / "QR.jpeg"


@app.get("/qr/QR.jpeg")
def qr_code() -> FileResponse:
    return FileResponse(QR_IMAGE_PATH, media_type="image/jpeg")

camera_registry = CameraRegistry()
detection_service = DetectionService(camera_registry)
alert_manager = AlertManager()
email_service = EmailAlertService(
    smtp_host=settings.smtp_host,
    smtp_port=settings.smtp_port,
    username=settings.smtp_user,
    password=settings.smtp_password,
    to_address=settings.alert_email_to,
)
rtsp_manager = RTSPStreamManager(settings.frame_store_dir)
yolo_service = YOLODetectionService(settings.yolo_model_path)
db_service = CameraDatabaseService()
active_camera_captures: dict[str, cv2.VideoCapture] = {}
camera_capture_locks: dict[str, threading.Lock] = {}
webcam_capture_threads: dict[str, threading.Thread] = {}
webcam_capture_stops: dict[str, threading.Event] = {}
latest_webcam_jpegs: dict[str, bytes] = {}
latest_camera_frames: dict[str, object] = {}
last_detection_times: dict[tuple[str, ThreatType], float] = {}
person_match_service = PersonMatchService()
last_person_match_times: dict[str, float] = {}
last_frame_failure_logs: dict[str, float] = {}
realtime_detection_task: asyncio.Task | None = None
subscription_reminder_task: asyncio.Task | None = None
alert_report_task: asyncio.Task | None = None
alert_report_service = AlertReportService()


def notify_alert(event) -> None:
    camera = camera_registry.get_camera(event.camera_id)
    location = camera.location if camera else "Unknown location"
    recipient = settings.alert_email_to
    if recipient == "admin@example.com" and settings.smtp_user != "your-gmail@gmail.com":
        recipient = settings.smtp_user
    alert_body = (
        f"CCTV AI Guard alert\n\n"
        f"Threat: {event.threat_type.value}\n"
        f"Camera: {event.camera_name}\n"
        f"Location: {location}\n"
        f"Date and time: {event.timestamp.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        f"Severity: {event.severity}/10\n\n"
        f"{event.message}"
    )
    email_service.send_alert(
        subject=f"ALERT: {event.threat_type.value.upper()} on {event.camera_name}",
        body=alert_body,
        image_path=event.image_path,
        to_address=recipient,
    )


def create_detection_alert(camera_id: str, threat: ThreatType, confidence: float, frame) -> dict:
    frame_path = os.path.join(
        settings.frame_store_dir,
        f"{camera_id}_{int(datetime.now(timezone.utc).timestamp() * 1000)}.jpg",
    )
    yolo_service.save_debug_frame(frame, frame_path)
    detection = detection_service.detect(camera_id, threat, confidence, image_path=frame_path)
    alert = detection_service.create_alert_event(detection)
    alert_manager.add_alert(alert)
    db_service.add_alert(
        alert.id,
        alert.camera_id,
        alert.camera_name,
        alert.threat_type.value,
        alert.severity,
        alert.message,
        alert.image_path,
        camera.location if (camera := camera_registry.get_camera(camera_id)) else None,
    )
    db_service.set_camera_alert(camera_id, alert.severity, CameraStatus.ALERT)
    notify_alert(alert)
    return alert.model_dump()


def create_person_match_alert(camera: Camera, frame) -> dict:
    timestamp = datetime.now(timezone.utc)
    detection_time = timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
    frame_path = os.path.join(settings.frame_store_dir, f"person_match_{camera.id}_{int(timestamp.timestamp() * 1000)}.jpg")
    yolo_service.save_debug_frame(frame, frame_path)
    event = AlertEvent(
        id=f"person-{timestamp.strftime('%Y%m%d%H%M%S%f')}",
        camera_id=camera.id,
        camera_name=camera.name,
        threat_type=ThreatType.PERSON_MATCH,
        severity=10,
        message=f"Tracked person detected on {camera.name} at {detection_time}.",
        timestamp=timestamp,
        image_path=frame_path,
    )
    alert_manager.add_alert(event)
    db_service.add_alert(event.id, event.camera_id, event.camera_name, event.threat_type.value, event.severity, event.message, event.image_path, camera.location)
    camera_registry.set_alert(camera.id, event.severity)
    db_service.set_camera_alert(camera.id, event.severity, CameraStatus.ALERT)
    notify_alert(event)
    return event.model_dump()


async def realtime_detection_loop() -> None:
    while True:
        for camera in camera_registry.list_cameras():
            frame = latest_camera_frames.get(camera.id)
            if frame is None and camera.rtsp_url.startswith("webcam://"):
                webcam_jpeg = latest_webcam_jpegs.get(camera.id)
                if webcam_jpeg:
                    frame = cv2.imdecode(np.frombuffer(webcam_jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                frame = await asyncio.to_thread(rtsp_manager.get_latest_frame, camera.rtsp_url)
            if frame is None:
                camera.status = CameraStatus.OFFLINE
                now = asyncio.get_running_loop().time()
                if now - last_frame_failure_logs.get(camera.id, 0.0) >= 15:
                    logging.getLogger(__name__).warning(
                        "No camera frame available for %s (%s); YOLO detection skipped.",
                        camera.name,
                        camera.rtsp_url,
                    )
                    last_frame_failure_logs[camera.id] = now
                continue
            if camera.status == CameraStatus.OFFLINE:
                camera.status = CameraStatus.ONLINE
            person_crops = await asyncio.to_thread(yolo_service.detect_person_crops, frame)
            person_detected = person_match_service.matches_person_crops(person_crops) if person_crops else person_match_service.matches(frame)
            if person_detected:
                now = asyncio.get_running_loop().time()
                if now - last_person_match_times.get(camera.id, 0.0) >= settings.detection_cooldown_seconds:
                    last_person_match_times[camera.id] = now
                    create_person_match_alert(camera, frame)
            threats, _ = await asyncio.to_thread(yolo_service.detect_threats, frame)
            now = asyncio.get_running_loop().time()
            for threat, confidence in threats:
                key = (camera.id, threat)
                if now - last_detection_times.get(key, 0.0) < settings.detection_cooldown_seconds:
                    continue
                last_detection_times[key] = now
                create_detection_alert(camera.id, threat, confidence, frame)
        await asyncio.sleep(settings.detection_interval_seconds)


async def subscription_reminder_loop() -> None:
    while True:
        try:
            check_and_send_expiring_soon_reminders()
        except Exception:
            pass
        await asyncio.sleep(3600)


async def alert_report_loop() -> None:
    while True:
        try:
            now = utc_now()
            for schedule in alert_report_service.due_schedules(now):
                end_at = now
                start_at = now - timedelta(hours=schedule.interval_hours)
                workbook = await asyncio.to_thread(alert_report_service.build_workbook, start_at, end_at)
                sent = await asyncio.to_thread(
                    email_service.send_attachment,
                    "CCTV AI Guard alert report",
                    f"Attached are the alerts from {start_at.isoformat()} to {end_at.isoformat()}.",
                    workbook,
                    f"alert-report-{now.strftime('%Y%m%d-%H%M')}.xlsx",
                    schedule.recipient_email,
                )
                if sent:
                    next_run = now + timedelta(hours=schedule.interval_hours)
                    alert_report_service.mark_sent(schedule.id, now, next_run)
        except Exception:
            pass
        await asyncio.sleep(60)


@app.on_event("startup")
async def start_realtime_detection() -> None:
    global realtime_detection_task, subscription_reminder_task, alert_report_task
    if settings.realtime_detection_enabled:
        realtime_detection_task = asyncio.create_task(realtime_detection_loop())
    subscription_reminder_task = asyncio.create_task(subscription_reminder_loop())
    alert_report_task = asyncio.create_task(alert_report_loop())


@app.on_event("shutdown")
async def stop_realtime_detection() -> None:
    if realtime_detection_task is not None:
        realtime_detection_task.cancel()
    if subscription_reminder_task is not None:
        subscription_reminder_task.cancel()
    if alert_report_task is not None:
        alert_report_task.cancel()


class SimulateAlertRequest(BaseModel):
    threat_type: str
    confidence: float = 0.9
    image_path: str | None = None


class CameraConnectRequest(BaseModel):
    name: str
    location: str
    rtsp_url: str
    connection_type: str = "rtsp"


class RemoveCameraRequest(BaseModel):
    password: str


class LoginForm(BaseModel):
    username: str
    password: str


class AlertReportRange(BaseModel):
    start_date: date
    end_date: date


class AlertReportScheduleRequest(BaseModel):
    interval_hours: int = Field(default=24, ge=1, le=168)
    email: str | None = None


async def get_current_user(request: Request):
    token = request.cookies.get("token")
    if not token:
        return None
    try:
        import jwt

        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        if payload.get("session_id") != app_session_id:
            return None
        username = payload.get("sub")
        return username
    except Exception:
        return None


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("terms.html", {"request": request})


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("privacy.html", {"request": request})


@app.get("/support", response_class=HTMLResponse)
async def support_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("support.html", {"request": request})


@app.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("forgot_password.html", {"request": request})


@app.get("/forgot-username", response_class=HTMLResponse)
async def forgot_username_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("forgot_username.html", {"request": request})


@app.post("/forgot-username", response_class=HTMLResponse)
async def forgot_username(request: Request, email: Annotated[str, Form()]) -> HTMLResponse:
    normalized_email = email.strip().lower()
    try:
        user = get_verified_user_by_email(normalized_email)
        if user:
            email_service.send_username_reminder(normalized_email, user["username"])
    except Exception:
        pass
    return templates.TemplateResponse("forgot_username.html", {"request": request, "message": "If a verified account uses that email, the username has been sent."})


@app.post("/forgot-password", response_class=HTMLResponse)
async def forgot_password(request: Request, email: Annotated[str, Form()]) -> HTMLResponse:
    normalized_email = email.strip().lower()
    try:
        code = create_password_reset_code(normalized_email)
        if code and email_service.send_password_reset_code(normalized_email, code):
            return RedirectResponse(url=f"/reset-password?email={normalized_email}", status_code=303)
    except Exception:
        pass
    return templates.TemplateResponse("forgot_password.html", {"request": request, "message": "If that email is registered, a reset code has been sent."})


@app.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request, email: str = "") -> HTMLResponse:
    return templates.TemplateResponse("reset_password.html", {"request": request, "email": email})


@app.post("/reset-password", response_class=HTMLResponse)
async def reset_password_route(
    request: Request,
    email: Annotated[str, Form()],
    code: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> HTMLResponse:
    if len(password) < 8:
        return templates.TemplateResponse("reset_password.html", {"request": request, "email": email, "error": "Password must be at least 8 characters."}, status_code=400)
    try:
        success = reset_password(email.strip().lower(), code.strip(), password)
    except Exception:
        success = False
    if not success:
        return templates.TemplateResponse("reset_password.html", {"request": request, "email": email, "error": "Invalid or expired reset code."}, status_code=400)
    return RedirectResponse(url="/login?reset=1", status_code=303)


@app.post("/login")
async def login(request: Request, username: Annotated[str, Form()], password: Annotated[str, Form()]) -> Response:
    try:
        user = authenticate_user(username.strip(), password)
    except Exception:
        return templates.TemplateResponse("login.html", {"request": request, "error": "We could not sign you in right now. Please try again."}, status_code=503)
    if not user:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Username or password is incorrect. Check your details and try again."}, status_code=401)
    token = create_token(user["username"], app_session_id)
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="token", value=token, httponly=True, samesite="lax", max_age=None, expires=None)
    return response


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("register.html", {"request": request})


@app.post("/register", response_class=HTMLResponse)
async def register(
    request: Request,
    name: Annotated[str, Form()],
    username: Annotated[str, Form()],
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> HTMLResponse:
    if len(password) < 8:
        return templates.TemplateResponse("register.html", {"request": request, "error": "Password must be at least 8 characters."}, status_code=400)
    try:
        normalized_email = email.strip().lower()
        normalized_username = username.strip()
        code = create_pending_user(name.strip(), normalized_username, normalized_email, password)
        if not email_service.send_verification_code(normalized_email, code):
            delete_pending_user(normalized_username)
            return templates.TemplateResponse("register.html", {"request": request, "error": "Verification email could not be sent. Check SMTP settings."}, status_code=502)
    except ValueError as error:
        return templates.TemplateResponse("register.html", {"request": request, "error": str(error)}, status_code=400)
    except Exception:
        raise HTTPException(status_code=503, detail="MongoDB is unavailable. Start MongoDB and try again.")
    return RedirectResponse(url=f"/verify?email={normalized_email}", status_code=303)


@app.get("/verify", response_class=HTMLResponse)
async def verify_page(request: Request, email: str = "") -> HTMLResponse:
    return templates.TemplateResponse("verify.html", {"request": request, "email": email})


@app.post("/verify", response_class=HTMLResponse)
async def verify(request: Request, email: Annotated[str, Form()], code: Annotated[str, Form()]) -> HTMLResponse:
    try:
        verified = verify_user_code(email.strip().lower(), code.strip())
    except PyMongoError:
        return templates.TemplateResponse("verify.html", {"request": request, "email": email, "error": "MongoDB connection failed. Check Atlas Network Access, database username, and password."}, status_code=503)
    except Exception:
        return templates.TemplateResponse("verify.html", {"request": request, "email": email, "error": "Verification could not be completed. Check the server log."}, status_code=500)
    if not verified:
        return templates.TemplateResponse("verify.html", {"request": request, "email": email, "error": "Invalid or expired verification code."}, status_code=400)
    return RedirectResponse(url="/login?verified=1", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, user=Depends(get_current_user)) -> HTMLResponse:
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request, next_path: str = "", username=Depends(get_current_user)) -> HTMLResponse:
    if not username:
        return RedirectResponse(url="/login", status_code=303)
    if next_path not in {"", "/profile/upgrade?source=dashboard"}:
        next_path = ""
    return templates.TemplateResponse("profile_verify.html", {"request": request, "next_path": next_path}, status_code=200)


@app.get("/profile/settings", response_class=HTMLResponse)
async def profile_settings_page(request: Request, username=Depends(get_current_user)) -> HTMLResponse:
    if not username:
        return RedirectResponse(url="/login", status_code=303)
    if request.cookies.get("profile_unlocked") != username:
        return RedirectResponse(url="/profile", status_code=303)
    user = get_user_by_username(username)
    subscription = get_user_subscription(username)
    plans = list_subscription_plans()
    return templates.TemplateResponse("profile.html", {"request": request, "user": user, "subscription": subscription, "plans": plans})


@app.get("/profile/upgrade", response_class=HTMLResponse)
async def profile_upgrade_page(request: Request, plan_code: str | None = None, source: str | None = None, username=Depends(get_current_user)) -> HTMLResponse:
    if not username:
        return RedirectResponse(url="/login", status_code=303)
    if source != "profile":
        return RedirectResponse(url="/profile/upgrade-protected", status_code=303)
    user = get_user_by_username(username)
    subscription = get_user_subscription(username)
    plans = list_subscription_plans()
    selected_plan_code = plan_code or subscription.get("plan_code", "free")
    if selected_plan_code not in {plan["code"] for plan in plans}:
        selected_plan_code = "free"
    return templates.TemplateResponse(
        "upgrade_plan.html",
        {"request": request, "user": user, "subscription": subscription, "plans": plans, "selected_plan_code": selected_plan_code},
    )


@app.get("/profile/upgrade-protected")
async def protected_upgrade_page(username=Depends(get_current_user)) -> RedirectResponse:
    if not username:
        return RedirectResponse(url="/login", status_code=303)
    return RedirectResponse(url="/profile?next_path=/profile/upgrade-direct", status_code=303)


@app.get("/profile/upgrade-direct", response_class=HTMLResponse)
async def profile_upgrade_direct_page(request: Request, plan_code: str | None = None, username=Depends(get_current_user)) -> HTMLResponse:
    if not username:
        return RedirectResponse(url="/login", status_code=303)
    user = get_user_by_username(username)
    subscription = get_user_subscription(username)
    plans = list_subscription_plans()
    selected_plan_code = plan_code or subscription.get("plan_code", "free")
    if selected_plan_code not in {plan["code"] for plan in plans}:
        selected_plan_code = "free"
    return templates.TemplateResponse(
        "upgrade_plan.html",
        {"request": request, "user": user, "subscription": subscription, "plans": plans, "selected_plan_code": selected_plan_code},
    )


@app.get("/profile/payment", response_class=HTMLResponse)
@app.get("/profile/payment/{plan_code}", response_class=HTMLResponse)
async def payment_page(request: Request, plan_code: str | None = None, username=Depends(get_current_user)) -> HTMLResponse:
    if not username:
        return RedirectResponse(url="/login", status_code=303)
    if request.cookies.get("profile_unlocked") != username:
        return RedirectResponse(url="/profile", status_code=303)

    if plan_code is None:
        plan_code = request.query_params.get("plan_code")

    if not plan_code:
        return RedirectResponse(url="/profile/upgrade", status_code=303)

    plans = list_subscription_plans()
    plan = next((item for item in plans if item["code"] == plan_code), None)
    if plan is None:
        return RedirectResponse(url="/profile/upgrade", status_code=303)

    user = get_user_by_username(username)
    return templates.TemplateResponse(
        "payment_method.html",
        {"request": request, "user": user, "plan": plan},
    )


@app.post("/profile/verify")
async def verify_profile_access(
    request: Request,
    password: Annotated[str, Form()],
    next_path: Annotated[str, Form()] = "",
    username=Depends(get_current_user),
) -> HTMLResponse:
    if not username:
        return RedirectResponse(url="/login", status_code=303)
    if next_path not in {"", "/profile/upgrade-direct"}:
        next_path = ""
    try:
        valid = bool(authenticate_user(username, password))
    except Exception:
        return templates.TemplateResponse("profile_verify.html", {"request": request, "error": "MongoDB is unavailable. Try again.", "next_path": next_path}, status_code=503)
    if not valid:
        return templates.TemplateResponse("profile_verify.html", {"request": request, "error": "Incorrect password.", "next_path": next_path}, status_code=401)
    response = RedirectResponse(url=next_path or "/profile/settings", status_code=303)
    response.set_cookie("profile_unlocked", username, httponly=True, samesite="lax", max_age=900)
    return response


@app.post("/profile/settings", response_class=HTMLResponse)
async def update_profile(
    request: Request,
    name: Annotated[str, Form()],
    email: Annotated[str, Form()],
    password: Annotated[str, Form()] = "",
    current_username=Depends(get_current_user),
) -> HTMLResponse:
    if not current_username:
        return RedirectResponse(url="/login", status_code=303)
    if request.cookies.get("profile_unlocked") != current_username:
        return RedirectResponse(url="/profile", status_code=303)
    try:
        user = update_user(current_username, name.strip(), email.strip().lower(), password)
    except ValueError as error:
        user = get_user_by_username(current_username)
        return templates.TemplateResponse("profile.html", {"request": request, "user": user, "subscription": get_user_subscription(current_username), "plans": list_subscription_plans(), "error": str(error)}, status_code=400)
    return templates.TemplateResponse("profile.html", {"request": request, "user": user, "subscription": get_user_subscription(current_username), "plans": list_subscription_plans(), "message": "Profile updated."})


@app.post("/profile/subscription/upgrade", response_class=HTMLResponse)
async def upgrade_subscription(
    request: Request,
    plan_code: Annotated[str, Form()],
    payment_method: Annotated[str, Form()] = "UPI",
    auto_renew: Annotated[str, Form()] = "off",
    card_number: Annotated[str, Form()] = "",
    card_expiry: Annotated[str, Form()] = "",
    card_cvv: Annotated[str, Form()] = "",
    account_number: Annotated[str, Form()] = "",
    ifsc_code: Annotated[str, Form()] = "",
    current_username=Depends(get_current_user),
) -> HTMLResponse:
    if not current_username:
        return RedirectResponse(url="/login", status_code=303)
    if request.cookies.get("profile_unlocked") != current_username:
        return RedirectResponse(url="/profile", status_code=303)
    try:
        payment_method_names = {
            "upi": "UPI",
            "card": "Card",
            "netbanking": "Net banking",
            "net banking": "Net banking",
        }
        normalized_payment_method = payment_method_names.get(payment_method.strip().lower(), "UPI")
        validation_error = None
        if normalized_payment_method == "Card":
            if not re.fullmatch(r"\d{4}\s?\d{4}\s?\d{4}\s?\d{4}", card_number.strip()):
                validation_error = "Enter a valid 16-digit card number."
            elif not re.fullmatch(r"(0[1-9]|1[0-2])/\d{2}", card_expiry.strip()):
                validation_error = "Enter the card expiry in MM/YY format."
            elif not re.fullmatch(r"\d{3,4}", card_cvv.strip()):
                validation_error = "Enter a valid 3 or 4 digit CVV."
        elif normalized_payment_method == "Net banking":
            if not re.fullmatch(r"\d{9,18}", account_number.strip()):
                validation_error = "Enter a valid account number."
            elif not re.fullmatch(r"[A-Za-z]{4}0[A-Za-z0-9]{6}", ifsc_code.strip()):
                validation_error = "Enter a valid IFSC code."
        if validation_error:
            user = get_user_by_username(current_username)
            return templates.TemplateResponse("payment_method.html", {"request": request, "plan": next((plan for plan in list_subscription_plans() if plan["code"] == plan_code), list_subscription_plans()[0]), "error": validation_error}, status_code=400)
        payment = process_subscription_payment(
            current_username,
            plan_code,
            auto_renew=(auto_renew.lower() in {"on", "true", "1", "yes"}),
            payment_method=normalized_payment_method,
        )
    except ValueError as error:
        user = get_user_by_username(current_username)
        return templates.TemplateResponse("profile.html", {"request": request, "user": user, "subscription": get_user_subscription(current_username), "plans": list_subscription_plans(), "error": str(error)}, status_code=400)
    user = get_user_by_username(current_username)
    email_sent = email_service.send_subscription_activation(
        email=user.get("email", ""),
        user_name=user.get("name") or user.get("username", current_username),
        payment=payment,
        subscription=get_user_subscription(current_username),
    )
    confirmation_message = payment["message"]
    if email_sent:
        confirmation_message += " Confirmation email sent."
    return templates.TemplateResponse("profile.html", {"request": request, "user": user, "subscription": get_user_subscription(current_username), "plans": list_subscription_plans(), "message": confirmation_message})


@app.post("/profile/subscription/auto-renew", response_class=HTMLResponse)
async def toggle_subscription_auto_renew(
    request: Request,
    enabled: Annotated[str, Form()] = "off",
    current_username=Depends(get_current_user),
) -> HTMLResponse:
    if not current_username:
        return RedirectResponse(url="/login", status_code=303)
    if request.cookies.get("profile_unlocked") != current_username:
        return RedirectResponse(url="/profile", status_code=303)
    subscription = toggle_auto_renew(current_username, enabled.lower() in {"on", "true", "1", "yes"})
    user = get_user_by_username(current_username)
    return templates.TemplateResponse("profile.html", {"request": request, "user": user, "subscription": get_user_subscription(current_username), "plans": list_subscription_plans(), "message": f"Auto-renew set to {'on' if subscription['auto_renew'] else 'off'}."})


@app.post("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("token")
    return response


def enforce_camera_limit_for_user(username: str | None = None) -> None:
    if not username:
        return
    subscription = get_user_subscription(username)
    allowed_count = 2 if subscription.get("status") == "expired" else int(subscription.get("max_cameras", 2))
    cameras = camera_registry.list_cameras()
    for camera in cameras[allowed_count:]:
        active_capture = active_camera_captures.pop(camera.id, None)
        if active_capture is not None:
            active_capture.release()
        latest_camera_frames.pop(camera.id, None)
        stop_event = webcam_capture_stops.pop(camera.id, None)
        if stop_event:
            stop_event.set()
        webcam_capture_threads.pop(camera.id, None)
        latest_webcam_jpegs.pop(camera.id, None)
        db_service.remove_camera(camera.id)
        camera_registry.remove_camera(camera.id)


@app.get("/api/cameras")
async def get_cameras(current_username=Depends(get_current_user)) -> dict:
    enforce_camera_limit_for_user(current_username)
    items = []
    for camera in camera_registry.list_cameras():
        items.append(camera.model_dump())
    return {"cameras": items}


@app.post("/api/cameras/connect")
async def connect_camera(payload: CameraConnectRequest, current_username=Depends(get_current_user)) -> dict:
    allowed_types = {"rtsp", "http", "webcam"}
    if payload.connection_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Unsupported camera connection type")
    allowed_schemes = {
        "rtsp": ("rtsp://", "rtsps://"),
        "http": ("http://", "https://"),
        "webcam": ("webcam://",),
    }
    if not payload.rtsp_url.startswith(allowed_schemes[payload.connection_type]):
        raise HTTPException(status_code=400, detail="The camera URL does not match the selected connection type")
    if not payload.name.strip() or not payload.location.strip():
        raise HTTPException(status_code=400, detail="Camera name and location are required")

    enforce_camera_limit_for_user(current_username)
    current_camera_count = len(camera_registry.list_cameras()) + 1
    if current_username:
        validation = validate_camera_limit(current_username, current_camera_count)
        if not validation["allowed"]:
            raise HTTPException(status_code=403, detail=validation["message"])

    camera_id = f"cam-{uuid.uuid4().hex[:8]}"
    camera = camera_registry.cameras[camera_id] = Camera(
        id=camera_id,
        name=payload.name.strip(),
        location=payload.location.strip(),
        rtsp_url=payload.rtsp_url,
        status=CameraStatus.ONLINE,
    )
    db_service.add_or_update_camera(camera.id, camera.name, camera.location, camera.rtsp_url)
    return {"status": "connected", "camera": camera.model_dump()}


@app.delete("/api/cameras/{camera_id}")
async def remove_camera(camera_id: str, payload: RemoveCameraRequest, current_username=Depends(get_current_user)) -> dict:
    if not current_username or not authenticate_user(current_username, payload.password):
        raise HTTPException(status_code=401, detail="Incorrect password")
    camera = camera_registry.get_camera(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    active_capture = active_camera_captures.pop(camera_id, None)
    if active_capture is not None:
        active_capture.release()
    latest_camera_frames.pop(camera_id, None)
    camera_capture_locks.pop(camera_id, None)
    stop_event = webcam_capture_stops.pop(camera_id, None)
    if stop_event:
        stop_event.set()
    webcam_capture_threads.pop(camera_id, None)
    latest_webcam_jpegs.pop(camera_id, None)
    image_paths = db_service.remove_camera(camera_id)
    camera_registry.remove_camera(camera_id)
    alert_manager.alerts = [alert for alert in alert_manager.alerts if alert.camera_id != camera_id]
    frame_store_dir = os.path.abspath(settings.frame_store_dir)
    for image_path in image_paths:
        if not image_path:
            continue
        absolute_path = os.path.abspath(image_path)
        if os.path.commonpath([frame_store_dir, absolute_path]) == frame_store_dir and os.path.isfile(absolute_path):
            os.remove(absolute_path)
    return {"status": "removed", "camera_id": camera_id}


def generate_camera_frames(camera_id: str, rtsp_url: str):
    cap = rtsp_manager.open_stream(rtsp_url)
    if not cap.isOpened():
        cap.release()
        yield _unavailable_frame()
        return
    active_camera_captures[camera_id] = cap

    try:
        while True:
            success, frame = cap.read()
            if not success:
                yield _unavailable_frame()
                break
            latest_camera_frames[camera_id] = frame
            success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if not success:
                continue
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + encoded.tobytes() + b"\r\n"
    finally:
        active_camera_captures.pop(camera_id, None)
        latest_camera_frames.pop(camera_id, None)
        cap.release()


def _unavailable_frame():
    frame = np.full((360, 640, 3), 233, dtype=np.uint8)
    cv2.putText(frame, "Camera stream unavailable", (145, 175), cv2.FONT_HERSHEY_SIMPLEX, 1, (82, 98, 116), 2, cv2.LINE_AA)
    cv2.putText(frame, "Check the stream address", (180, 215), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (82, 98, 116), 2, cv2.LINE_AA)
    success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not success:
        return b"--frame\r\nContent-Type: image/jpeg\r\n\r\n\r\n"
    return b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + encoded.tobytes() + b"\r\n"


def _webcam_capture_loop(camera_id: str, rtsp_url: str, stop_event: threading.Event) -> None:
    capture = None
    try:
        while not stop_event.is_set():
            if capture is None or not capture.isOpened():
                if capture is not None:
                    capture.release()
                capture = rtsp_manager.open_stream(rtsp_url)
                if not capture.isOpened():
                    time.sleep(0.5)
                    continue

            success, frame = capture.read()
            if not success or frame is None:
                capture.release()
                capture = None
                time.sleep(0.25)
                continue

            success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if success:
                latest_webcam_jpegs[camera_id] = encoded.tobytes()
    finally:
        if capture is not None:
            capture.release()
        webcam_capture_threads.pop(camera_id, None)
        webcam_capture_stops.pop(camera_id, None)


def _start_webcam_capture(camera_id: str, rtsp_url: str) -> None:
    if camera_id in webcam_capture_threads:
        return
    stop_event = threading.Event()
    capture_thread = threading.Thread(
        target=_webcam_capture_loop,
        args=(camera_id, rtsp_url, stop_event),
        daemon=True,
    )
    webcam_capture_stops[camera_id] = stop_event
    webcam_capture_threads[camera_id] = capture_thread
    capture_thread.start()


def generate_webcam_frames(camera_id: str):
    while True:
        jpeg = latest_webcam_jpegs.get(camera_id)
        if jpeg is None:
            jpeg = _unavailable_jpeg()
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
        time.sleep(0.1)


@app.get("/api/cameras/{camera_id}/video")
async def camera_video(camera_id: str):
    camera = camera_registry.get_camera(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    if camera.rtsp_url.startswith("webcam://"):
        _start_webcam_capture(camera_id, camera.rtsp_url)
        return StreamingResponse(
            generate_webcam_frames(camera_id),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )
    return StreamingResponse(
        generate_camera_frames(camera_id, camera.rtsp_url),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/api/cameras/{camera_id}/snapshot")
async def camera_snapshot(camera_id: str):
    camera = camera_registry.get_camera(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    _start_webcam_capture(camera_id, camera.rtsp_url)

    jpeg = latest_webcam_jpegs.get(camera_id)
    if jpeg is None:
        return Response(content=_unavailable_jpeg(), media_type="image/jpeg")
    camera.status = CameraStatus.ONLINE
    return Response(content=jpeg, media_type="image/jpeg")


def _unavailable_jpeg():
    frame = np.full((360, 640, 3), 233, dtype=np.uint8)
    cv2.putText(frame, "Camera stream unavailable", (145, 175), cv2.FONT_HERSHEY_SIMPLEX, 1, (82, 98, 116), 2, cv2.LINE_AA)
    cv2.putText(frame, "Retrying connection...", (190, 215), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (82, 98, 116), 2, cv2.LINE_AA)
    success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return encoded.tobytes() if success else b""


@app.get("/api/alerts")
async def get_alerts() -> dict:
    connected_camera_ids = {camera.id for camera in camera_registry.list_cameras()}
    alerts = [
        alert for alert in db_service.list_alerts()
        if alert.camera_id in connected_camera_ids
    ][:10]
    return {
        "alerts": [
            {
                "id": alert.id,
                "camera_id": alert.camera_id,
                "camera_name": alert.camera_name,
                "threat_type": alert.threat_type,
                "severity": alert.severity,
                "message": alert.message,
                "timestamp": (alert.timestamp.replace(tzinfo=timezone.utc) if alert.timestamp.tzinfo is None else alert.timestamp).isoformat(),
                "image_path": alert.image_path,
            }
            for alert in alerts
        ],
    }


def _report_email_for_user(username: str, requested_email: str | None = None) -> str:
    user = get_user_by_username(username)
    email = (requested_email or (user or {}).get("email") or settings.alert_email_to).strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Add a valid email address to your profile before sending reports.")
    return email


@app.get("/api/alerts/export")
async def export_alert_report(
    start_date: date,
    end_date: date,
    current_username=Depends(get_current_user),
) -> StreamingResponse:
    if not current_username:
        raise HTTPException(status_code=401, detail="Please sign in to download alert reports.")
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="End date must be on or after the start date.")
    start_at, end_at = date_range(start_date, end_date)
    workbook = await asyncio.to_thread(alert_report_service.build_workbook, start_at, end_at)
    filename = f"alert-report-{start_date.isoformat()}-to-{end_date.isoformat()}.xlsx"
    return StreamingResponse(
        workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/alerts/report-email")
async def email_alert_report(payload: AlertReportRange, current_username=Depends(get_current_user)) -> dict:
    if not current_username:
        raise HTTPException(status_code=401, detail="Please sign in to email alert reports.")
    if payload.end_date < payload.start_date:
        raise HTTPException(status_code=400, detail="End date must be on or after the start date.")
    recipient = _report_email_for_user(current_username)
    start_at, end_at = date_range(payload.start_date, payload.end_date)
    workbook = await asyncio.to_thread(alert_report_service.build_workbook, start_at, end_at)
    sent = await asyncio.to_thread(
        email_service.send_attachment,
        "CCTV AI Guard alert report",
        f"Attached are the alerts from {payload.start_date.isoformat()} to {payload.end_date.isoformat()}.",
        workbook,
        f"alert-report-{payload.start_date.isoformat()}-to-{payload.end_date.isoformat()}.xlsx",
        recipient,
    )
    if not sent:
        raise HTTPException(status_code=502, detail="The report could not be emailed. Check the SMTP settings.")
    return {"status": "sent", "email": recipient}


@app.get("/api/alerts/report-schedule")
async def get_alert_report_schedule(current_username=Depends(get_current_user)) -> dict:
    if not current_username:
        raise HTTPException(status_code=401, detail="Please sign in to view report scheduling.")
    schedule = alert_report_service.get_schedule(current_username)
    if schedule is None:
        return {"schedule": None}
    return {
        "schedule": {
            "enabled": bool(schedule.enabled),
            "interval_hours": schedule.interval_hours,
            "email": schedule.recipient_email,
            "next_run_at": schedule.next_run_at.isoformat(),
            "last_sent_at": schedule.last_sent_at.isoformat() if schedule.last_sent_at else None,
        }
    }


@app.post("/api/alerts/report-schedule")
async def save_alert_report_schedule(
    payload: AlertReportScheduleRequest,
    current_username=Depends(get_current_user),
) -> dict:
    if not current_username:
        raise HTTPException(status_code=401, detail="Please sign in to schedule alert reports.")
    recipient = _report_email_for_user(current_username, payload.email)
    schedule = alert_report_service.save_schedule(current_username, recipient, payload.interval_hours)
    return {
        "status": "scheduled",
        "schedule": {
            "enabled": True,
            "interval_hours": schedule.interval_hours,
            "email": schedule.recipient_email,
            "next_run_at": schedule.next_run_at.isoformat(),
        },
    }


@app.delete("/api/alerts/report-schedule")
async def disable_alert_report_schedule(current_username=Depends(get_current_user)) -> dict:
    if not current_username:
        raise HTTPException(status_code=401, detail="Please sign in to manage report scheduling.")
    alert_report_service.disable_schedule(current_username)
    return {"status": "disabled"}


@app.post("/api/person-monitor")
async def configure_person_monitor(
    name: Annotated[str, Form()] = "Tracked person",
    images: list[UploadFile] = File(...),
    current_username=Depends(get_current_user),
) -> dict:
    if not current_username:
        raise HTTPException(status_code=401, detail="Please sign in to configure person monitoring.")
    if not images or len(images) > 5:
        raise HTTPException(status_code=400, detail="Upload between 1 and 5 reference pictures.")
    os.makedirs(settings.frame_store_dir, exist_ok=True)
    reference_paths = []
    for index, image in enumerate(images):
        if not image.content_type or not image.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Every reference file must be an image.")
        image_bytes = await image.read()
        if not image_bytes or len(image_bytes) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Each reference image must be smaller than 10 MB.")
        if len(image_bytes) < 100:
            raise HTTPException(status_code=400, detail="One selected image is empty or invalid.")
        reference_path = os.path.join(settings.frame_store_dir, f"person_reference_{index}.jpg")
        with open(reference_path, "wb") as reference_file:
            reference_file.write(image_bytes)
        reference_paths.append(reference_path)
    try:
        person_match_service.set_references(name, reference_paths)
    except ValueError as error:
        for reference_path in reference_paths:
            if os.path.exists(reference_path):
                os.remove(reference_path)
        raise HTTPException(status_code=400, detail=str(error))
    last_person_match_times.clear()
    return {"status": "monitoring", "name": person_match_service.reference_name, "pictures": len(reference_paths)}


@app.delete("/api/person-monitor")
async def clear_person_monitor(current_username=Depends(get_current_user)) -> dict:
    if not current_username:
        raise HTTPException(status_code=401, detail="Please sign in to stop person monitoring.")
    person_match_service.clear_reference()
    last_person_match_times.clear()
    return {"status": "stopped"}


@app.post("/api/cameras/{camera_id}/simulate-activity")
async def simulate_activity(camera_id: str, payload: SimulateAlertRequest) -> dict:
    try:
        threat = ThreatType(payload.threat_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid threat_type provided.")

    frame_path = payload.image_path or os.path.join(settings.frame_store_dir, f"{camera_id}_{int(datetime.now(timezone.utc).timestamp())}.jpg")
    os.makedirs(os.path.dirname(frame_path), exist_ok=True)
    if not os.path.exists(frame_path):
        image_placeholder = os.path.join(settings.frame_store_dir, "placeholder.jpg")
        if os.path.exists(image_placeholder):
            frame_path = image_placeholder

    result = detection_service.detect(
        camera_id=camera_id,
        threat_type=threat,
        confidence=payload.confidence,
        image_path=frame_path,
    )
    event = detection_service.create_alert_event(result)
    alert_manager.add_alert(event)
    db_service.add_alert(event.id, event.camera_id, event.camera_name, event.threat_type.value, event.severity, event.message, event.image_path, camera.location if (camera := camera_registry.get_camera(camera_id)) else None)
    db_service.set_camera_alert(camera_id, event.severity, CameraStatus.ALERT)

    notify_alert(event)

    return {"status": "alert_created", "alert": event.model_dump()}


@app.post("/api/test-alert")
async def test_alert() -> dict:
    camera = camera_registry.list_cameras()[0]
    detection = detection_service.detect(
        camera_id=camera.id,
        threat_type=ThreatType.INTRUSION,
        confidence=0.96,
    )
    event = detection_service.create_alert_event(detection)
    alert_manager.add_alert(event)
    db_service.add_alert(event.id, event.camera_id, event.camera_name, event.threat_type.value, event.severity, event.message, event.image_path, camera.location)
    db_service.set_camera_alert(camera.id, event.severity, CameraStatus.ALERT)
    notify_alert(event)
    return {"status": "ok", "alert": event.model_dump()}


@app.post("/api/alerts/clear")
async def clear_alerts() -> dict:
    alert_manager.alerts.clear()
    for camera in camera_registry.list_cameras():
        camera_registry.clear_alert(camera.id)
    return {"status": "cleared"}


@app.post("/api/cameras/{camera_id}/process")
async def process_camera(camera_id: str) -> dict:
    camera = camera_registry.get_camera(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    frame = rtsp_manager.get_latest_frame(camera.rtsp_url)
    if frame is None:
        return {"status": "no_frame", "camera_id": camera_id}
    threats, boxes = yolo_service.detect_threats(frame)
    if threats:
        threat, confidence = max(threats, key=lambda item: item[1])
        alert = create_detection_alert(camera_id, threat, confidence, frame)
        return {"status": "alert_created", "alert": alert, "detections": boxes}
    return {"status": "ok", "camera_id": camera_id, "detections": boxes}


@app.post("/api/cameras/{camera_id}/capture")
async def capture_frame(camera_id: str) -> dict:
    camera = camera_registry.get_camera(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    image_path = rtsp_manager.capture_frame(camera.rtsp_url)
    if not image_path:
        raise HTTPException(status_code=500, detail="Failed to capture camera frame")
    return {"status": "captured", "image_path": image_path}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
