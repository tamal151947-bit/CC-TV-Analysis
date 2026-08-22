from __future__ import annotations

from typing import List

from app.models import AlertEvent, ThreatType


class AlertManager:
    def __init__(self) -> None:
        self.alerts: List[AlertEvent] = []

    def add_alert(self, alert: AlertEvent) -> AlertEvent:
        self.alerts.insert(0, alert)
        return alert

    def list_alerts(self) -> List[AlertEvent]:
        return self.alerts

    def get_latest_alerts(self, limit: int = 10) -> List[AlertEvent]:
        return self.alerts[:limit]

    def get_alert_count_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for alert in self.alerts:
            counts[alert.threat_type.value] = counts.get(alert.threat_type.value, 0) + 1
        return counts

    def has_active_alerts(self) -> bool:
        return len(self.alerts) > 0
