# CCTV AI Security Monitoring Platform

This project is a starter for a real-time CCTV monitoring system that can evaluate multiple cameras, detect suspicious behavior, trigger alerts, and notify an admin.

## Main features

- Multi-camera registry for 50+ CCTV streams
- Suspicious activity categories:
  - theft
  - intrusion
  - violence
  - missing object
  - suspicious activity
- Camera state tracking with red alert mode
- Popup-style alert events in the dashboard
- Alert email service using Gmail SMTP settings
- FastAPI backend with a simple HTML dashboard
- MongoDB-backed user registration and profiles
- Email verification before first login
- Real-time background detection while cameras are connected

## Project structure

- app/main.py: application entrypoint
- app/config.py: environment configuration
- app/models.py: data models
- app/services/: detection, camera management, alerts, email sending
- app/templates/index.html: dashboard UI
- app/static/: CSS and static assets

## Quick start

1. Create a virtual environment
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```
2. Install dependencies
   ```bash
   pip install -r requirements.txt
   ```
3. Copy environment variables
   ```bash
   copy .env.example .env
   ```
4. Update Gmail SMTP values in .env
5. Start the app
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```
6. Open http://localhost:8000

## User accounts

Start MongoDB locally, or set `MONGODB_URL` to a MongoDB Atlas connection string in `.env`.
Set `SMTP_USER` and `SMTP_PASSWORD` to a Gmail account and Gmail app password so registration verification codes can be delivered.
Users register at `/register`, verify the six-digit code sent by email, then log in with only their username and password.
After login, open `/profile` to update name, email, or password. Passwords are hashed before storage in MongoDB.

## API endpoints

- GET /
- GET /api/cameras
- GET /api/alerts
- POST /api/test-alert
- POST /api/cameras/{camera_id}/simulate-activity

## Notes

Real-time detection runs once per second by default. Configure it in `.env` with `REALTIME_DETECTION_ENABLED`, `DETECTION_INTERVAL_SECONDS`, and `DETECTION_COOLDOWN_SECONDS`.

The bundled `yolov8n.pt` model detects general objects. It maps `person` or `intruder` to possible home intrusion. Accurate theft, robbery, stealing, fight, violence, and harassment detection requires a custom YOLO model trained with labels such as `theft`, `robbery`, `fight`, `violence`, or `harassment`; set its path with `YOLO_MODEL_PATH`. A general object model must not be treated as reliable proof of those behaviors.
