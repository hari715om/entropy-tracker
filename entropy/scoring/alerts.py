"""
Alert Engine — evaluates alert rules against module scores.

Fires alerts when modules cross configurable thresholds:
- entropy_score > 85 → CRITICAL
- knowledge_score > 90 → CRITICAL
- bus_factor == 1 → HIGH
- trend_per_month > 5 → WATCH
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from entropy.scoring.scorer import ModuleScore

logger = logging.getLogger(__name__)


@dataclass
class AlertRule:
    """A single alert rule definition."""

    field: str
    operator: str  # ">", ">=", "==", "<", "<="
    threshold: float
    severity: str  # CRITICAL, HIGH, WATCH


@dataclass
class Alert:
    """A fired alert."""

    id: str = field(default_factory=lambda: str(uuid4()))
    module_path: str = ""
    severity: str = ""
    message: str = ""
    fired_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "module_path": self.module_path,
            "severity": self.severity,
            "message": self.message,
            "fired_at": self.fired_at.isoformat(),
            "resolved": self.resolved,
        }


# Default alert rules matching the plan
DEFAULT_ALERT_RULES: list[AlertRule] = [
    AlertRule(field="entropy_score", operator=">", threshold=85, severity="CRITICAL"),
    AlertRule(field="knowledge_score", operator=">", threshold=90, severity="CRITICAL"),
    AlertRule(field="bus_factor", operator="==", threshold=1, severity="HIGH"),
    AlertRule(field="trend_per_month", operator=">", threshold=5, severity="WATCH"),
]


def _compare(value: float, operator: str, threshold: float) -> bool:
    ops = {
        ">": lambda a, b: a > b,
        ">=": lambda a, b: a >= b,
        "==": lambda a, b: a == b,
        "<": lambda a, b: a < b,
        "<=": lambda a, b: a <= b,
    }
    fn = ops.get(operator)
    return fn(value, threshold) if fn else False


def _build_message(rule: AlertRule, value: float, module_path: str) -> str:
    field_labels = {
        "entropy_score": "Entropy score",
        "knowledge_score": "Knowledge decay",
        "dep_score": "Dependency decay",
        "churn_score": "Churn score",
        "age_score": "Age score",
        "bus_factor": "Bus factor",
        "trend_per_month": "Trend",
    }
    label = field_labels.get(rule.field, rule.field)
    return f"{label} for {module_path} is {value:.1f} ({rule.operator} {rule.threshold})"


class AlertEngine:
    """Evaluate alert rules against a set of module scores."""

    def __init__(self, rules: list[AlertRule] | None = None):
        self.rules = rules or DEFAULT_ALERT_RULES

    def evaluate(self, scores: dict[str, ModuleScore]) -> list[Alert]:
        """
        Check all modules against all rules.
        Returns a list of fired alerts.
        """
        alerts: list[Alert] = []

        for path, score in scores.items():
            for rule in self.rules:
                value = getattr(score, rule.field, None)
                if value is None:
                    continue

                if _compare(float(value), rule.operator, rule.threshold):
                    alert = Alert(
                        module_path=path,
                        severity=rule.severity,
                        message=_build_message(rule, float(value), path),
                    )
                    alerts.append(alert)
                    logger.info("Alert fired: [%s] %s", rule.severity, alert.message)

        return alerts
