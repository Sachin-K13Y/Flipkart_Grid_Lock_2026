"""
api/routes_dashboard.py — Dashboard summary and full report export for ParkIQ.

Provides:
    GET /dashboard        — Aggregate stats for the 4 summary cards.
    GET /export/report    — Full JSON report (dashboard + clusters + time stats + recommendations).
"""

from datetime import datetime

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter()


def get_app_state() -> dict:
    """
    Lazily import and return the shared app_state dict from main.py.

    Using a deferred import avoids circular dependency issues at module load
    time (main.py imports this router, so a top-level 'from main import ...'
    would create a cycle).
    """
    from main import app_state  # noqa: PLC0415  (deferred import by design)
    return app_state


def _to_python(value):
    """
    Recursively convert numpy scalars / arrays to Python native types so that
    FastAPI's JSONResponse can serialise them without error.
    """
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {k: _to_python(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_python(item) for item in value]
    return value


# ---------------------------------------------------------------------------
# GET /dashboard
# ---------------------------------------------------------------------------

@router.get("/dashboard")
def get_dashboard() -> JSONResponse:
    """
    Return high-level summary metrics for the dashboard cards.

    Returns
    -------
    200 JSONResponse  ::
        {
          "total_violations":       <int>,
          "active_clusters":        <int>,
          "critical_zones":         <int>,
          "avg_resolution_minutes": <float>,
          "last_updated":           "<ISO-8601 string>",
          "date_range":             {"from": "<ISO>", "to": "<ISO>"}
        }

    400 HTTPException
        Raised when no data has been loaded yet.
    """
    state = get_app_state()

    if state["df"] is None:
        raise HTTPException(
            status_code=400,
            detail="No data loaded. Please upload a CSV first.",
        )

    df = state["df"]
    clusters = state["clusters"]

    # --- total violations (all rows in the cleaned / labelled DataFrame) ---
    total_violations = int(len(df))

    # --- active clusters (excludes noise label -1) ---
    active_clusters = 0
    if clusters is not None and not clusters.empty:
        active_clusters = int(len(clusters))

    # --- critical zones ---
    critical_zones = 0
    if (
        clusters is not None
        and not clusters.empty
        and "priority_tier" in clusters.columns
    ):
        critical_zones = int((clusters["priority_tier"] == "Critical").sum())

    # --- avg resolution minutes ---
    avg_resolution_minutes = 0.0
    if "resolution_minutes" in df.columns:
        mean_val = df["resolution_minutes"].mean()
        # mean() returns NaN if no valid values exist
        if mean_val != mean_val:  # NaN check without importing math
            avg_resolution_minutes = 0.0
        else:
            avg_resolution_minutes = round(float(mean_val), 1)

    # --- date range ---
    date_range = {"from": "", "to": ""}
    if "created_datetime" in df.columns:
        date_strings = df["created_datetime"].dropna().astype(str)
        if not date_strings.empty:
            date_range = {
                "from": min(date_strings),
                "to":   max(date_strings),
            }

    # --- last updated ---
    last_updated = state.get("last_updated") or datetime.utcnow().isoformat()

    return JSONResponse(
        content={
            "total_violations":       total_violations,
            "active_clusters":        active_clusters,
            "critical_zones":         critical_zones,
            "avg_resolution_minutes": avg_resolution_minutes,
            "last_updated":           last_updated,
            "date_range":             date_range,
        }
    )


# ---------------------------------------------------------------------------
# GET /export/report
# ---------------------------------------------------------------------------

@router.get("/export/report")
def export_report() -> JSONResponse:
    """
    Return a full JSON report suitable for download or external processing.

    Returns
    -------
    200 JSONResponse  ::
        {
          "generated_at":    "<ISO-8601 string>",
          "dashboard":       { ...same as GET /dashboard... },
          "clusters":        [ ...list of cluster dicts... ],
          "time_stats":      { ...temporal analysis dict... },
          "recommendations": [ ...list of recommendation dicts... ]
        }

    400 HTTPException
        Raised when no data has been loaded yet.
    """
    state = get_app_state()

    if state["df"] is None:
        raise HTTPException(
            status_code=400,
            detail="No data loaded. Please upload a CSV first.",
        )

    df = state["df"]
    clusters = state["clusters"]

    # ------------------------------------------------------------------
    # Dashboard section (reuse the same logic, avoid a second HTTP call)
    # ------------------------------------------------------------------
    total_violations = int(len(df))

    active_clusters = 0
    if clusters is not None and not clusters.empty:
        active_clusters = int(len(clusters))

    critical_zones = 0
    if (
        clusters is not None
        and not clusters.empty
        and "priority_tier" in clusters.columns
    ):
        critical_zones = int((clusters["priority_tier"] == "Critical").sum())

    avg_resolution_minutes = 0.0
    if "resolution_minutes" in df.columns:
        mean_val = df["resolution_minutes"].mean()
        if mean_val != mean_val:
            avg_resolution_minutes = 0.0
        else:
            avg_resolution_minutes = round(float(mean_val), 1)

    date_range = {"from": "", "to": ""}
    if "created_datetime" in df.columns:
        date_strings = df["created_datetime"].dropna().astype(str)
        if not date_strings.empty:
            date_range = {
                "from": min(date_strings),
                "to":   max(date_strings),
            }

    last_updated = state.get("last_updated") or datetime.utcnow().isoformat()

    dashboard_section = {
        "total_violations":       total_violations,
        "active_clusters":        active_clusters,
        "critical_zones":         critical_zones,
        "avg_resolution_minutes": avg_resolution_minutes,
        "last_updated":           last_updated,
        "date_range":             date_range,
    }

    # ------------------------------------------------------------------
    # Clusters section — convert DataFrame rows to plain dicts
    # ------------------------------------------------------------------
    clusters_list: list[dict] = []
    if clusters is not None and not clusters.empty:
        for record in clusters.to_dict(orient="records"):
            clusters_list.append(_to_python(record))

    # ------------------------------------------------------------------
    # Time stats section
    # ------------------------------------------------------------------
    time_stats = _to_python(state.get("time_stats") or {})

    # ------------------------------------------------------------------
    # Recommendations section
    # ------------------------------------------------------------------
    recommendations = _to_python(state.get("recommendations") or [])

    return JSONResponse(
        content={
            "generated_at":    datetime.utcnow().isoformat(),
            "dashboard":       dashboard_section,
            "clusters":        clusters_list,
            "time_stats":      time_stats,
            "recommendations": recommendations,
        }
    )
