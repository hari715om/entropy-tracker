"""
Alerts router — query and manage alerts.

Endpoints:
- GET  /repos/{id}/alerts     Active alerts for a repo
- POST /alerts/{id}/resolve   Mark an alert as resolved
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from entropy.storage.db import get_session
from entropy.storage.models import AlertRecord, Repo

router = APIRouter()


@router.get("/repos/{repo_id}/alerts")
async def get_alerts(
    repo_id: str,
    severity: str | None = Query(default=None, description="Filter by severity"),
    resolved: bool = Query(default=False, description="Include resolved alerts"),
) -> list[dict[str, Any]]:
    """Get active alerts for a repository."""
    try:
        rid = uuid.UUID(repo_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    with get_session() as session:
        repo = session.query(Repo).filter_by(id=rid).first()
        if not repo:
            raise HTTPException(status_code=404, detail="Repo not found")

        query = session.query(AlertRecord).filter(AlertRecord.repo_id == rid)

        if not resolved:
            query = query.filter(AlertRecord.resolved == False)  # noqa: E712

        if severity:
            query = query.filter(AlertRecord.severity == severity.upper())

        alerts = query.order_by(AlertRecord.fired_at.desc()).all()
        return [a.to_dict() for a in alerts]


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: str) -> dict[str, Any]:
    """Mark an alert as resolved."""
    try:
        aid = uuid.UUID(alert_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    with get_session() as session:
        alert = session.query(AlertRecord).filter_by(id=aid).first()
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")

        alert.resolved = True
        return alert.to_dict()
