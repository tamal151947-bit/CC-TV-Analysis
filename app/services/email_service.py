from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


class EmailAlertService:
    def __init__(self, smtp_host: str, smtp_port: int, username: str, password: str, to_address: str) -> None:
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.to_address = to_address

    def send_alert(self, subject: str, body: str, image_path: str | None = None, to_address: str | None = None) -> bool:
        if not self.username or not self.password:
            return False
        try:
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = self.username
            msg["To"] = to_address or self.to_address
            msg.set_content(body)

            if image_path and os.path.exists(image_path):
                with open(image_path, "rb") as f:
                    image_data = f.read()
                msg.add_attachment(
                    image_data,
                    maintype="image",
                    subtype="jpeg",
                    filename=os.path.basename(image_path),
                )

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as smtp:
                smtp.starttls()
                smtp.login(self.username, self.password)
                smtp.send_message(msg)
            return True
        except Exception:
            return False

    def send_verification_code(self, email: str, code: str) -> bool:
        if not self.username or not self.password:
            return False
        try:
            msg = EmailMessage()
            msg["Subject"] = "Verify your CCTV AI Guard account"
            msg["From"] = self.username
            msg["To"] = email
            msg.set_content(f"Your verification code is {code}. It expires in 15 minutes.")
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as smtp:
                smtp.starttls()
                smtp.login(self.username, self.password)
                smtp.send_message(msg)
            return True
        except Exception:
            return False

    def send_password_reset_code(self, email: str, code: str) -> bool:
        if not self.username or not self.password:
            return False
        try:
            msg = EmailMessage()
            msg["Subject"] = "Reset your CCTV AI Guard password"
            msg["From"] = self.username
            msg["To"] = email
            msg.set_content(f"Your password reset code is {code}. It expires in 15 minutes.")
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as smtp:
                smtp.starttls()
                smtp.login(self.username, self.password)
                smtp.send_message(msg)
            return True
        except Exception:
            return False

    def send_username_reminder(self, email: str, username: str) -> bool:
        if not self.username or not self.password:
            return False
        try:
            msg = EmailMessage()
            msg["Subject"] = "Your CCTV AI Guard username"
            msg["From"] = self.username
            msg["To"] = email
            msg.set_content(f"Your CCTV AI Guard username is: {username}")
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as smtp:
                smtp.starttls()
                smtp.login(self.username, self.password)
                smtp.send_message(msg)
            return True
        except Exception:
            return False
