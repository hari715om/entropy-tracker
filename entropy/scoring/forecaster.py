"""
Trajectory Forecaster — computes decay velocity and projects future scores.

Uses linear regression on historical entropy scores to determine:
- trend_per_month: how fast entropy is changing (positive = decaying)
- forecast: projected score at 30, 60, 90 days
- estimated_unmaintainable: days until score hits 100
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class Forecast:
    """Projection of future entropy scores."""

    current_score: float
    trend_per_month: float  # positive = getting worse
    score_30d: float = 0.0
    score_60d: float = 0.0
    score_90d: float = 0.0
    days_to_unmaintainable: int | None = None  # days until score reaches 100

    def to_dict(self) -> dict:
        return {
            "current_score": round(self.current_score, 1),
            "trend_per_month": round(self.trend_per_month, 2),
            "score_30d": round(self.score_30d, 1),
            "score_60d": round(self.score_60d, 1),
            "score_90d": round(self.score_90d, 1),
            "days_to_unmaintainable": self.days_to_unmaintainable,
        }


def compute_trajectory(scores: list[float], timestamps_days: list[float]) -> float:
    """
    Compute entropy change per month using linear regression.

    Parameters
    ----------
    scores : historical entropy scores
    timestamps_days : corresponding timestamps as days from epoch (or any monotonic scale)

    Returns
    -------
    slope normalized to per-month change.
    Positive = decaying (getting worse). Negative = improving.
    """
    if len(scores) < 2:
        return 0.0

    try:
        coeffs = np.polyfit(timestamps_days, scores, 1)
        slope = coeffs[0]
        return round(slope * 30.44, 2)  # normalize to per-month
    except (np.linalg.LinAlgError, ValueError):
        return 0.0


def forecast_score(current_score: float, trend_per_month: float, days: int) -> float:
    """Project entropy score forward by *days*. Capped at 0–100."""
    projected = current_score + trend_per_month * (days / 30.44)
    return round(min(max(projected, 0), 100), 1)


def build_forecast(
    current_score: float,
    historical_scores: list[float] | None = None,
    historical_timestamps_days: list[float] | None = None,
    trend_override: float | None = None,
) -> Forecast:
    """
    Build a full forecast for a module.

    Either provide historical data to auto-compute trend, or pass ``trend_override``.
    """
    if trend_override is not None:
        trend = trend_override
    elif historical_scores and historical_timestamps_days:
        trend = compute_trajectory(historical_scores, historical_timestamps_days)
    else:
        trend = 0.0

    fc = Forecast(
        current_score=current_score,
        trend_per_month=trend,
        score_30d=forecast_score(current_score, trend, 30),
        score_60d=forecast_score(current_score, trend, 60),
        score_90d=forecast_score(current_score, trend, 90),
    )

    # Estimated days to unmaintainable (score = 100)
    if trend > 0 and current_score < 100:
        remaining = 100 - current_score
        days_needed = remaining / trend * 30.44
        fc.days_to_unmaintainable = int(days_needed)

    return fc
