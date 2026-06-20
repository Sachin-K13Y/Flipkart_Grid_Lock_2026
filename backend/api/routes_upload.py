"""
api/routes_upload.py — CSV upload and full pipeline execution for ParkIQ.

Provides:
    POST /upload  — Accept a multipart CSV upload, save it to
                    backend/data/violations.csv, run the full processing
                    pipeline, cache results in app_state, and return a
                    summary response.
"""

import os
import time
from datetime import datetime

from fastapi import APIRouter, File, HTTPException, UploadFile
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


# ---------------------------------------------------------------------------
# POST /upload
# ---------------------------------------------------------------------------

@router.post("/upload")
async def upload_csv(file: UploadFile = File(...)) -> JSONResponse:
    """
    Accept a CSV file, persist it, run the full analytics pipeline, and
    cache the results in app_state.

    Returns
    -------
    200 JSONResponse
        {
          "status": "success",
          "message": "Data loaded and processed successfully",
          "records_processed": <int>,
          "clusters_found": <int>,
          "critical_zones": <int>,
          "pipeline_timing_seconds": {
            "load": <float>,
            "cluster": <float>,
            "score": <float>,
            "time_stats": <float>,
            "recommendations": <float>
          }
        }

    400 HTTPException
        Raised if the file is not a CSV or if any pipeline step fails.
    """
    # ------------------------------------------------------------------
    # 1. Validate that the upload is a CSV
    # ------------------------------------------------------------------
    filename = file.filename or ""
    is_csv_extension = filename.lower().endswith(".csv")
    is_csv_content_type = (file.content_type or "").lower() in (
        "text/csv",
        "application/csv",
        "application/vnd.ms-excel",
        "text/plain",  # some browsers send this for .csv
    )

    # Allow if either signal confirms CSV. Reject only when both disagree.
    if not is_csv_extension and not is_csv_content_type:
        raise HTTPException(status_code=400, detail="Please upload a CSV file.")

    # ------------------------------------------------------------------
    # 2. Determine save path and persist the file
    # ------------------------------------------------------------------
    # Resolve: <this file's directory> / .. / data / violations.csv
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    data_dir = os.path.abspath(data_dir)
    os.makedirs(data_dir, exist_ok=True)

    filepath = os.path.join(data_dir, "violations.csv")

    try:
        contents = await file.read()
        with open(filepath, "wb") as fout:
            fout.write(contents)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to save uploaded file: {exc}",
        ) from exc

    # ------------------------------------------------------------------
    # 3. Run the full analytics pipeline (with per-stage timing)
    # ------------------------------------------------------------------
    try:
        from core.loader import load_and_clean
        from core.clustering import run_dbscan, get_cluster_summaries
        from core.impact_scorer import compute_impact_scores
        from core.time_analysis import compute_temporal_stats
        from core.recommender import generate_enforcement_recommendations

        # --- Stage 1: Load & clean ---
        t0 = time.time()
        df = load_and_clean(filepath)
        t1 = time.time()

        # --- Stage 2: Cluster ---
        df_labeled = run_dbscan(df)
        labels = df_labeled["cluster_label"].values
        cluster_summaries = get_cluster_summaries(df_labeled, labels)
        t2 = time.time()

        # --- Stage 3: Score ---
        scored_clusters = compute_impact_scores(cluster_summaries)
        t3 = time.time()

        # --- Stage 4: Temporal stats ---
        time_stats = compute_temporal_stats(df)
        t4 = time.time()

        # --- Stage 5: AI recommendations ---
        recommendations = generate_enforcement_recommendations(scored_clusters, top_n=5)
        t5 = time.time()

    except HTTPException:
        raise  # pass through any already-formed HTTP errors
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Pipeline failed: {exc}",
        ) from exc

    # ------------------------------------------------------------------
    # 4. Store results in shared app_state
    # ------------------------------------------------------------------
    state = get_app_state()
    state["df"] = df_labeled
    state["clusters"] = scored_clusters
    state["time_stats"] = time_stats
    state["recommendations"] = recommendations
    state["last_updated"] = datetime.utcnow().isoformat()

    # ------------------------------------------------------------------
    # 5. Compute summary metrics for the response
    # ------------------------------------------------------------------
    records_processed = int(len(df_labeled))

    clusters_found = (
        int(len(scored_clusters)) if not scored_clusters.empty else 0
    )

    critical_zones = 0
    if not scored_clusters.empty and "priority_tier" in scored_clusters.columns:
        critical_zones = int(
            (scored_clusters["priority_tier"] == "Critical").sum()
        )

    pipeline_timing = {
        "load":            round(t1 - t0, 4),
        "cluster":         round(t2 - t1, 4),
        "score":           round(t3 - t2, 4),
        "time_stats":      round(t4 - t3, 4),
        "recommendations": round(t5 - t4, 4),
    }

    return JSONResponse(
        content={
            "status": "success",
            "message": "Data loaded and processed successfully",
            "records_processed": records_processed,
            "clusters_found": clusters_found,
            "critical_zones": critical_zones,
            "pipeline_timing_seconds": pipeline_timing,
        }
    )
