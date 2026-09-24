from __future__ import annotations

import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from io import BytesIO


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

    def send_attachment(self, subject: str, body: str, attachment: BytesIO, filename: str, to_address: str) -> bool:
        if not self.username or not self.password or not to_address:
            return False
        try:
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = self.username
            msg["To"] = to_address
            msg.set_content(body)
            msg.add_attachment(
                attachment.getvalue(),
                maintype="application",
                subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                filename=filename,
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

    def send_subscription_reminder(self, email: str, plan_name: str, expires_at: str | None = None) -> bool:
        if not self.username or not self.password:
            return False
        try:
            msg = EmailMessage()
            msg["Subject"] = "CCTV AI Guard subscription renewal reminder"
            msg["From"] = self.username
            msg["To"] = email
            renewal_text = f"Your {plan_name} plan expires on {expires_at or 'soon'}. Please renew before the expiry date to avoid interruption."
            msg.set_content(renewal_text)
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as smtp:
                smtp.starttls()
                smtp.login(self.username, self.password)
                smtp.send_message(msg)
            return True
        except Exception:
            return False

    def send_subscription_activation(
        self,
        email: str,
        user_name: str,
        payment: dict,
        subscription: dict,
    ) -> bool:
        if not email or not self.username or not self.password:
            return False

        plan_code = payment.get("plan_code", "free")
        plan_name = payment.get("plan_name", "Free")
        start_at = self._format_datetime(subscription.get("last_paid_at"))
        expiry_at = self._format_datetime(subscription.get("expires_at"))
        purchase_date = start_at.strftime("%d %B %Y")
        purchase_time = start_at.strftime("%I:%M %p")
        start_date = purchase_date
        expiry_date = expiry_at.strftime("%d %B %Y")
        amount = payment.get("amount_paid_inr", 0)
        transaction_id = payment.get("gateway_reference", "Not available")
        payment_method = payment.get("payment_method", "UPI")
        camera_limit = subscription.get("max_cameras", 0)

        plan_sections = {
            "silver": (
                "🥈 CCTV AI Guard – Silver Plan Activated",
                "Your CCTV AI Guard Silver Plan has been successfully activated.",
                "Smarter Monitoring. Better Protection.",
                [
                    "✅ Live Monitoring",
                    "✅ AI Smart Alerts",
                    "📸 Incident Pictures Sent to Email",
                    f"📹 Up to {camera_limit} Cameras",
                    "🔔 Smart Security Notifications",
                    "✅ 30-Day Access",
                ],
            ),
            "gold": (
                "🥇 CCTV AI Guard – Gold Plan Activated",
                "Congratulations! Your CCTV AI Guard Gold Plan has been successfully activated.",
                "24/7 AI Monitoring. One Smart Security Solution.",
                [
                    "✅ Live Monitoring",
                    "✅ AI Smart Alerts",
                    "📸 Incident Pictures Sent to Email",
                    f"📹 Up to {camera_limit} Cameras",
                    "📄 Daily PDF Security Report",
                    "🕛 Daily report covers 12:00 AM – 11:59 PM",
                    "📊 Detailed AI Activity Summary",
                    "🔔 Advanced Security Alerts",
                    "✅ 30-Day Access",
                ],
            ),
            "diamond": (
                "💎 CCTV AI Guard – Diamond Plan Activated",
                "Congratulations! Your CCTV AI Guard Diamond Plan has been successfully activated.",
                "Maximum Cameras. Maximum Intelligence. Maximum Protection.",
                [
                    "✅ Live Monitoring",
                    "✅ AI Smart Alerts",
                    "📸 Real-Time Incident Pictures Sent to Email",
                    f"📹 Up to {camera_limit} Cameras",
                    "📄 Daily PDF Security Report",
                    "🕛 Daily report covers 12:00 AM – 11:59 PM",
                    "📊 Detailed AI Activity Summary",
                    "🔔 Priority Security Alerts",
                    "🎯 Advanced Multi-Camera Monitoring",
                    "🛡️ Complete Daily Security Overview",
                    "✅ 30-Day Access",
                    "🛡️ All-in-One AI Protection",
                ],
            ),
        }
        subject, introduction, closing, features = plan_sections.get(
            plan_code,
            (
                f"CCTV AI Guard – {plan_name} Plan Activated",
                f"Your CCTV AI Guard {plan_name} Plan has been successfully activated.",
                "Smart monitoring for your security needs.",
                ["✅ Live Monitoring", "✅ AI Smart Alerts", f"📹 Up to {camera_limit} Cameras", "✅ 30-Day Access"],
            ),
        )
        body = "\n".join(
            [
                subject,
                "",
                f"Hello {user_name},",
                "",
                introduction,
                "",
                "SUBSCRIPTION DETAILS",
                f"Plan: {plan_name}",
                f"Amount Paid: ₹{amount}",
                f"Purchase Date: {purchase_date}",
                f"Purchase Time: {purchase_time}",
                f"Plan Start Date: {start_date}",
                f"Plan Expiry Date: {expiry_date}",
                f"Transaction ID: {transaction_id}",
                f"Payment Method: {payment_method}",
                f"Cameras: Up to {camera_limit}",
                "Access Period: 30 days",
                "",
                "INCLUDED FEATURES",
                *[f"- {feature}" for feature in features],
                "",
                closing,
                "",
                "Whenever AI detects an important security event, an incident picture will be sent directly to your email.",
                "",
                "Regards,",
                "CCTV AI Guard Team",
            ]
        )
        return self._send_message(subject, body, email)

    @staticmethod
    def _format_datetime(value: str | None) -> datetime:
        if value:
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                pass
        return datetime.now()

    def _send_message(self, subject: str, body: str, to_address: str) -> bool:
        if not self.username or not self.password:
            return False
        try:
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = self.username
            msg["To"] = to_address
            msg.set_content(body)
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as smtp:
                smtp.starttls()
                smtp.login(self.username, self.password)
                smtp.send_message(msg)
            return True
        except Exception:
            return False
