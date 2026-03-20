"""
Modules router — query module-level entropy data.

Endpoints:
- GET /repos/{id}/modules          All modules sorted by entropy score
- GET /repos/{id}/modules/{path}   Single module: full breakdown + history + forecast
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from entropy.scoring.forecaster import build_forecast
from entropy.storage.db import get_latest_scores, get_module_history, get_session
from entropy.storage.models import Repo

router = APIRouter()


@router.get("/repos/{repo_id}/modules")
async def list_modules(
    repo_id: str,
    top: int = Query(default=0, description="Return only top N worst modules"),
    severity: str | None = Query(default=None, description="Filter by severity: CRITICAL, HIGH, MEDIUM, HEALTHY"),
) -> list[dict[str, Any]]:
    """All modules with current scores, sorted by entropy (descending)."""
    try:
        rid = uuid.UUID(repo_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    with get_session() as session:
        repo = session.query(Repo).filter_by(id=rid).first()
        if not repo:
            raise HTTPException(status_code=404, detail="Repo not found")

        scores = get_latest_scores(session, rid)
        results = [s.to_dict() for s in scores]

        # Add severity labels
        for r in results:
            score = r["entropy_score"]
            if score >= 85:
                r["severity"] = "CRITICAL"
            elif score >= 70:
                r["severity"] = "HIGH"
            elif score >= 50:
                r["severity"] = "MEDIUM"
            else:
                r["severity"] = "HEALTHY"

        # Filter by severity
        if severity:
            results = [r for r in results if r["severity"] == severity.upper()]

        # Limit to top N
        if top > 0:
            results = results[:top]

        return results


@router.get("/repos/{repo_id}/modules/{module_path:path}")
async def get_module(repo_id: str, module_path: str) -> dict[str, Any]:
    """Full signal breakdown + history + forecast for a single module."""
    try:
        rid = uuid.UUID(repo_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    with get_session() as session:
        repo = session.query(Repo).filter_by(id=rid).first()
        if not repo:
            raise HTTPException(status_code=404, detail="Repo not found")

        # Get latest score
        latest_scores = get_latest_scores(session, rid)
        current = None
        for s in latest_scores:
            if s.module_path == module_path:
                current = s
                break

        if current is None:
            raise HTTPException(status_code=404, detail=f"Module not found: {module_path}")

        # Get history for forecast
        history = get_module_history(session, rid, module_path, limit=180)

        # Build forecast
        if len(history) >= 2:
            scores_list = [h.entropy_score for h in reversed(history)]
            timestamps_list = [
                (h.time.timestamp() / 86400) for h in reversed(history)  # days from epoch
            ]
            fc = build_forecast(current.entropy_score, scores_list, timestamps_list)
        else:
            fc = build_forecast(current.entropy_score, trend_override=0.0)

        # Build response
        result = current.to_dict()
        result["forecast"] = fc.to_dict()
        result["history"] = [
            {
                "date": h.time.isoformat(),
                "entropy_score": h.entropy_score,
                "knowledge_score": h.knowledge_score,
                "dep_score": h.dep_score,
                "churn_score": h.churn_score,
                "age_score": h.age_score,
            }
            for h in reversed(history[-90:])  # last 90 data points
        ]

        # Severity label
        score = result["entropy_score"]
        if score >= 85:
            result["severity"] = "CRITICAL"
        elif score >= 70:
            result["severity"] = "HIGH"
        elif score >= 50:
            result["severity"] = "MEDIUM"
        else:
            result["severity"] = "HEALTHY"

        return result
