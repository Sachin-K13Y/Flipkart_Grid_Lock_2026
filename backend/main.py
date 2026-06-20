"""
main.py — FastAPI application entry point for ParkIQ.

Defines the shared in-memory app_state (imported by all route modules),
registers all API routers, enables CORS, and auto-loads synthetic data
on startup so the dashboard is immediately usable without a CSV upload.
"""

import os
import sys
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
# FastAPI application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="ParkIQ API",
    version="1.0.0",
    description="AI-Driven Parking Violation Intelligence System",
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
    return {"status": "ok", "message": "ParkIQ API running"}


# ---------------------------------------------------------------------------
# Startup: auto-load synthetic data so the dashboard works immediately
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup_load_synthetic_data():
    """
    Run the full analytics pipeline on synthetic data at server startup.

    This populates app_state so all dashboard endpoints return meaningful
    data even before the user uploads a real CSV file.  Errors are caught
    and logged to stdout; they do NOT abort the server startup.
    """
    try:
        from core.loader import generate_synthetic_data
        from core.clustering import run_dbscan, get_cluster_summaries
        from core.impact_scorer import compute_impact_scores
        from core.time_analysis import compute_temporal_stats
        from core.recommender import generate_enforcement_recommendations

        print("ParkIQ: Loading synthetic data for demo...")

        # Stage 1: Generate synthetic dataset
        df = generate_synthetic_data()

        # Stage 2: Cluster with DBSCAN
        df_labeled = run_dbscan(df)
        labels = df_labeled["cluster_label"].values
        cluster_summaries = get_cluster_summaries(df_labeled, labels)

        # Stage 3: Compute impact scores
        scored_clusters = compute_impact_scores(cluster_summaries)

        # Stage 4: Temporal stats
        time_stats = compute_temporal_stats(df)

        # Stage 5: AI enforcement recommendations (top 5 clusters)
        recommendations = generate_enforcement_recommendations(scored_clusters, top_n=5)

        # Store results in shared state
        app_state["df"] = df_labeled
        app_state["clusters"] = scored_clusters
        app_state["time_stats"] = time_stats
        app_state["recommendations"] = recommendations
        app_state["last_updated"] = datetime.utcnow().isoformat()

        print(
            f"ParkIQ: Synthetic data loaded. "
            f"{len(df)} records, {len(scored_clusters)} clusters."
        )

    except Exception as e:
        print(f"ParkIQ: Warning — synthetic data startup failed: {e}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
