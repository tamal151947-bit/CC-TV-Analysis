from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font
from app.database import SessionLocal
from app.models import AlertRecord, AlertReportSchedule
from app.services.database_service import CameraDatabaseService


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def local_timezone():
    return datetime.now().astimezone().tzinfo or timezone.utc


def date_range(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    local_tz = local_timezone()
    start_local = datetime.combine(start_date, datetime.min.time(), tzinfo=local_tz)
    end_local = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=local_tz)
    # SQLite stores alert timestamps as UTC without timezone metadata.
    return start_local.astimezone(timezone.utc).replace(tzinfo=None), end_local.astimezone(timezone.utc).replace(tzinfo=None)


class AlertReportService:
    def list_alerts(self, start_at: datetime, end_at: datetime) -> list[AlertRecord]:
        return CameraDatabaseService().list_alerts_between(start_at, end_at)

    def build_workbook(self, start_at: datetime, end_at: datetime) -> BytesIO:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Alerts"
        headers = ["Date and time (local)", "Camera number / ID", "Camera name", "Location", "Threat type", "Severity", "Message", "Alert ID"]
        sheet.append(headers)
        for cell in sheet[1]:
            cell.font = Font(bold=True)

        alerts = self.list_alerts(start_at, end_at)
        for alert in alerts:
            sheet.append([
                self._as_utc(alert.timestamp).astimezone(local_timezone()).replace(tzinfo=None),
                alert.camera_id,
                alert.camera_name,
                alert.camera_location,
                alert.threat_type,
                alert.severity,
                alert.message,
                alert.id,
            ])
        sheet.freeze_panes = "A2"
        for cell in sheet["A"][1:]:
            cell.number_format = "yyyy-mm-dd hh:mm:ss"
        widths = {"A": 24, "B": 24, "C": 24, "D": 24, "E": 22, "F": 10, "G": 72, "H": 28}
        for column, width in widths.items():
            sheet.column_dimensions[column].width = width
        output = BytesIO()
        workbook.save(output)
        output.seek(0)
        return output

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @staticmethod
    def _camera_location(camera_id: str) -> str:
        from app.database import SessionLocal
        from app.models import CameraRecord

        with SessionLocal() as session:
            camera = session.query(CameraRecord).filter(CameraRecord.id == camera_id).first()
            return camera.location if camera else "Unknown location"

    def get_schedule(self, username: str) -> AlertReportSchedule | None:
        with SessionLocal() as session:
            return session.query(AlertReportSchedule).filter(AlertReportSchedule.username == username).first()

    def save_schedule(self, username: str, recipient_email: str, interval_hours: int) -> AlertReportSchedule:
        now = utc_now()
        with SessionLocal() as session:
            schedule = session.query(AlertReportSchedule).filter(AlertReportSchedule.username == username).first()
            if schedule is None:
                schedule = AlertReportSchedule(username=username, recipient_email=recipient_email)
                session.add(schedule)
            schedule.recipient_email = recipient_email
            schedule.interval_hours = interval_hours
            schedule.enabled = 1
            schedule.next_run_at = now + timedelta(hours=interval_hours)
            session.commit()
            session.refresh(schedule)
            return schedule

    def disable_schedule(self, username: str) -> bool:
        with SessionLocal() as session:
            schedule = session.query(AlertReportSchedule).filter(AlertReportSchedule.username == username).first()
            if schedule is None:
                return False
            schedule.enabled = 0
            session.commit()
            return True

    def due_schedules(self, now: datetime) -> list[AlertReportSchedule]:
        with SessionLocal() as session:
            return (
                session.query(AlertReportSchedule)
                .filter(and_(AlertReportSchedule.enabled == 1, AlertReportSchedule.next_run_at <= now))
                .all()
            )

    def mark_sent(self, schedule_id: int, sent_at: datetime, next_run_at: datetime) -> None:
        with SessionLocal() as session:
            schedule = session.query(AlertReportSchedule).filter(AlertReportSchedule.id == schedule_id).first()
            if schedule:
                schedule.last_sent_at = sent_at
                schedule.next_run_at = next_run_at
                session.commit()