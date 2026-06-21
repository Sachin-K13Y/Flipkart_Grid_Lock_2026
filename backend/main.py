"""
main.py — FastAPI application entry point for ParkIQ.

Defines the shared in-memory app_state (imported by all route modules),
registers all API routers, enables CORS, and auto-loads synthetic data
on startup so the dashboard is immediately usable without a CSV upload.
"""

import os
import sys
import threading
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes_upload import router as upload_router
from api.routes_dashboard import router as dashboard_router
from api.routes_hotspots import router as hotspots_router
from api.routes_ai_insights import router as ai_insights_router

# ---------------------------------------------------------------------------
# Shared in-memory state — imported by all route modules via:
#     from main import app_state
#
# Must be defined at module level (not inside any function) so that the
# deferred import pattern used in route modules works correctly.
# ---------------------------------------------------------------------------
app_state = {
    "df": None,
    "clusters": None,
    "time_stats": None,
    "recommendations": None,
    "last_updated": None,
}


# ---------------------------------------------------------------------------
# Background loader — runs in a thread so it never blocks the server from
# accepting requests, and never OOM-kills the process during startup.
# ---------------------------------------------------------------------------

def _load_synthetic_data_background():
    """
    Load real parking violation data from precomputed_data.json.

    Falls back to generating synthetic data if the JSON file is not found.
    Runs in a background thread so the server health-check passes immediately.
    """
    import time
    import json as _json
    import os as _os

    time.sleep(2)  # Let the server bind and pass health-check first

    json_path = _os.path.join(_os.path.dirname(__file__), "data", "precomputed_data.json")

    # ── Try loading pre-computed real data first ────────────────────────────
    if _os.path.exists(json_path):
        try:
            print("ParkIQ: Loading precomputed real data...", flush=True)
            with open(json_path, "r") as f:
                data = _json.load(f)

            import pandas as pd

            # Reconstruct minimal DataFrames from JSON
            clusters_df = pd.DataFrame(data.get("clusters", []))
            if not clusters_df.empty and "impact_score" not in clusters_df.columns:
                # Add impact_score if missing (older JSON)
                clusters_df["impact_score"] = clusters_df.get("violation_count", 0) / 10

            # Build a lightweight df from map_points for hotspot endpoints
            mp = data.get("map_points", [])
            df = pd.DataFrame(mp) if mp else pd.DataFrame()
            if not df.empty:
                df = df.rename(columns={"violation_type": "vtype"})

            app_state["df"]              = df
            app_state["clusters"]        = clusters_df
            app_state["time_stats"]      = data.get("time_stats", {})
            app_state["recommendations"] = None   # Will be fetched from /api/recommendations
            app_state["last_updated"]    = data.get("dashboard", {}).get("last_updated",
                                            datetime.utcnow().isoformat())
            # Stash dashboard summary for /api/dashboard endpoint
            app_state["dashboard"]       = data.get("dashboard", {})

            total = data.get("dashboard", {}).get("total_violations", 0)
            nclusters = len(clusters_df)
            print(f"ParkIQ: Loaded real data — {total:,} violations, {nclusters} clusters.", flush=True)
            return

        except Exception as e:
            print(f"ParkIQ: precomputed JSON load failed: {e} — falling back to synthetic.", flush=True)

    # ── Fallback: generate synthetic data ───────────────────────────────────
    try:
        from core.loader import generate_synthetic_data
        from core.clustering import run_dbscan, get_cluster_summaries
        from core.impact_scorer import compute_impact_scores
        from core.time_analysis import compute_temporal_stats
        from core.recommender import generate_enforcement_recommendations

        print("ParkIQ: Generating synthetic demo data...", flush=True)
        df = generate_synthetic_data()
        df_labeled = run_dbscan(df)
        labels = df_labeled["cluster_label"].values
        cluster_summaries = get_cluster_summaries(df_labeled, labels)
        scored_clusters = compute_impact_scores(cluster_summaries)
        time_stats = compute_temporal_stats(df)
        recommendations = generate_enforcement_recommendations(scored_clusters, top_n=5)

        app_state["df"]              = df_labeled
        app_state["clusters"]        = scored_clusters
        app_state["time_stats"]      = time_stats
        app_state["recommendations"] = recommendations
        app_state["last_updated"]    = datetime.utcnow().isoformat()
        app_state["dashboard"]       = {}

        print(f"ParkIQ: Synthetic data ready — {len(df)} records.", flush=True)
    except Exception as e:
        print(f"ParkIQ: Warning — data load failed: {e}", flush=True)


# ---------------------------------------------------------------------------
# Lifespan — starts the background loader thread after the server is up
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: kick off the background thread
    t = threading.Thread(target=_load_synthetic_data_background, daemon=True)
    t.start()
    yield
    # Shutdown: nothing to clean up (thread is daemon, will die with process)


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="ParkIQ API",
    version="1.0.0",
    description="AI-Driven Parking Violation Intelligence System",
    lifespan=lifespan,
)

# Enable CORS for all origins (development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Register routers
# ---------------------------------------------------------------------------
app.include_router(upload_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(hotspots_router, prefix="/api")
app.include_router(ai_insights_router, prefix="/api")


# ---------------------------------------------------------------------------
# Root health-check endpoint
# ---------------------------------------------------------------------------
@app.get("/")
def root():
    ready = app_state["df"] is not None
    return {
        "status": "ok",
        "message": "ParkIQ API running",
        "data_ready": ready,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
