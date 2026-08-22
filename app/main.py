from __future__ import annotations

import os
import secrets
import uuid
import asyncio
from datetime import datetime, timezone
from typing import Annotated

import cv2
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pymongo.errors import PyMongoError

from app.config import get_settings
from app.database import init_db
from app.models import Camera, CameraStatus, ThreatType
from app.services.alert_service import AlertManager
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
from app.services.rtsp_service import RTSPStreamManager
from app.services.yolo_service import YOLODetectionService

settings = get_settings()
init_db()
app_session_id = secrets.token_urlsafe(32)

app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

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
latest_camera_frames: dict[str, object] = {}
last_detection_times: dict[tuple[str, ThreatType], float] = {}
realtime_detection_task: asyncio.Task | None = None


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
    )
    db_service.set_camera_alert(camera_id, alert.severity, CameraStatus.ALERT)
    notify_alert(alert)
    return alert.model_dump()


async def realtime_detection_loop() -> None:
    while True:
        for camera in camera_registry.list_cameras():
            frame = latest_camera_frames.get(camera.id)
            if frame is None:
                frame = await asyncio.to_thread(rtsp_manager.get_latest_frame, camera.rtsp_url)
            if frame is None:
                continue
            threats, _ = await asyncio.to_thread(yolo_service.detect_threats, frame)
            now = asyncio.get_running_loop().time()
            for threat, confidence in threats:
                key = (camera.id, threat)
                if now - last_detection_times.get(key, 0.0) < settings.detection_cooldown_seconds:
                    continue
                last_detection_times[key] = now
                create_detection_alert(camera.id, threat, confidence, frame)
        await asyncio.sleep(settings.detection_interval_seconds)


@app.on_event("startup")
async def start_realtime_detection() -> None:
    global realtime_detection_task
    if settings.realtime_detection_enabled:
        realtime_detection_task = asyncio.create_task(realtime_detection_loop())


@app.on_event("shutdown")
async def stop_realtime_detection() -> None:
    if realtime_detection_task is not None:
        realtime_detection_task.cancel()


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
async def profile_page(request: Request, username=Depends(get_current_user)) -> HTMLResponse:
    if not username:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("profile_verify.html", {"request": request}, status_code=200)


@app.get("/profile/settings", response_class=HTMLResponse)
async def profile_settings_page(request: Request, username=Depends(get_current_user)) -> HTMLResponse:
    if not username:
        return RedirectResponse(url="/login", status_code=303)
    if request.cookies.get("profile_unlocked") != username:
        return RedirectResponse(url="/profile", status_code=303)
    user = get_user_by_username(username)
    return templates.TemplateResponse("profile.html", {"request": request, "user": user})


@app.post("/profile/verify")
async def verify_profile_access(
    request: Request,
    password: Annotated[str, Form()],
    username=Depends(get_current_user),
) -> HTMLResponse:
    if not username:
        return RedirectResponse(url="/login", status_code=303)
    try:
        valid = bool(authenticate_user(username, password))
    except Exception:
        return templates.TemplateResponse("profile_verify.html", {"request": request, "error": "MongoDB is unavailable. Try again."}, status_code=503)
    if not valid:
        return templates.TemplateResponse("profile_verify.html", {"request": request, "error": "Incorrect password."}, status_code=401)
    response = RedirectResponse(url="/profile/settings", status_code=303)
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
        return templates.TemplateResponse("profile.html", {"request": request, "user": user, "error": str(error)}, status_code=400)
    return templates.TemplateResponse("profile.html", {"request": request, "user": user, "message": "Profile updated."})


@app.post("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("token")
    return response


@app.get("/api/cameras")
async def get_cameras() -> dict:
    items = []
    for camera in camera_registry.list_cameras():
        items.append(camera.model_dump())
    return {"cameras": items}


@app.post("/api/cameras/connect")
async def connect_camera(payload: CameraConnectRequest) -> dict:
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
        return
    active_camera_captures[camera_id] = cap

    try:
        while True:
            success, frame = cap.read()
            if not success:
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


@app.get("/api/cameras/{camera_id}/video")
async def camera_video(camera_id: str):
    camera = camera_registry.get_camera(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    return StreamingResponse(
        generate_camera_frames(camera_id, camera.rtsp_url),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/api/alerts")
async def get_alerts() -> dict:
    return {"alerts": [alert.model_dump() for alert in alert_manager.get_latest_alerts(20)]}


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
    db_service.add_alert(event.id, event.camera_id, event.camera_name, event.threat_type.value, event.severity, event.message, event.image_path)
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
    db_service.add_alert(event.id, event.camera_id, event.camera_name, event.threat_type.value, event.severity, event.message, event.image_path)
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
