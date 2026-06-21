"""
api/routes_hotspots.py — Hotspot, heatmap, and temporal-stats routes for ParkIQ.

Provides:
    GET /hotspots        — GeoJSON FeatureCollection of cluster markers
    GET /heatmap-data    — lat/lon/weight points for the heatmap layer
    GET /time-stats      — Full temporal analysis dict
    GET /top-junctions   — Top 10 junctions list
"""

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter()

_NO_DATA_DETAIL = "No data loaded. Please upload a CSV first."


def get_app_state() -> dict:
    """
    Lazily import and return the shared app_state dict from main.py.

    Deferred import avoids the circular dependency that would arise if we
    imported app_state at module level (main.py imports this router).
    """
    from main import app_state  # noqa: PLC0415  (deferred import by design)
    return app_state


# ---------------------------------------------------------------------------
# Helper: coerce a single value to a JSON-safe Python type
# ---------------------------------------------------------------------------

def _json_safe(value):
    """
    Convert numpy scalars, pandas NA-likes, lists, and other non-serialisable
    objects to their closest JSON-safe Python equivalent.
    """
    if value is None:
        return None
    # numpy integer types
    if isinstance(value, (np.integer,)):
        return int(value)
    # numpy floating types
    if isinstance(value, (np.floating,)):
        f = float(value)
        return None if (f != f or f == float("inf") or f == float("-inf")) else f
    # numpy bool
    if isinstance(value, np.bool_):
        return bool(value)
    # plain Python float — guard NaN / Inf
    if isinstance(value, float):
        return None if (value != value or value == float("inf") or value == float("-inf")) else value
    # lists / numpy arrays — recurse
    if isinstance(value, (list, np.ndarray)):
        return [_json_safe(v) for v in value]
    # everything else (str, int, bool, None) is already safe
    return value


# ---------------------------------------------------------------------------
# GET /hotspots
# ---------------------------------------------------------------------------

@router.get("/hotspots")
async def get_hotspots() -> JSONResponse:
    """
    Return a GeoJSON FeatureCollection whose features are the cluster centroids.

    Each Feature carries all cluster fields as properties.  If no clusters are
    available an empty FeatureCollection is returned (not a 400 error) so the
    map layer can safely handle the "no data yet" state.
    """
    state = get_app_state()
    clusters = state.get("clusters")

    # Empty / not-yet-loaded → return empty FeatureCollection
    if clusters is None or (hasattr(clusters, "empty") and clusters.empty):
        return JSONResponse(content={"type": "FeatureCollection", "features": []})

    features = []
    for _, row in clusters.iterrows():
        lat = float(row["centroid_lat"])
        lon = float(row["centroid_lon"])

        properties = {
            "cluster_id":                  int(row["cluster_id"]),
            "violation_count":             int(row["violation_count"]),
            "dominant_violation_type":     str(row.get("dominant_violation_type", "")),
            "peak_hour_ratio":             _json_safe(row.get("peak_hour_ratio", 0.0)),
            "avg_resolution_minutes":      _json_safe(row.get("avg_resolution_minutes", 0.0)),
            "impact_score":                _json_safe(row.get("impact_score", 0.0)),
            "priority_tier":               str(row.get("priority_tier", "")),
            "priority_color":              str(row.get("priority_color", "")),
            "recommended_enforcement_time": str(row.get("recommended_enforcement_time", "")),
            "junctions_covered":           _json_safe(row.get("junctions_covered", [])),
            "police_stations_involved":    _json_safe(row.get("police_stations_involved", [])),
            "first_seen":                  str(row["first_seen"]) if row.get("first_seen") is not None else None,
            "last_seen":                   str(row["last_seen"])  if row.get("last_seen")  is not None else None,
        }

        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [lon, lat],  # GeoJSON order: [longitude, latitude]
            },
            "properties": properties,
        }
        features.append(feature)

    return JSONResponse(content={"type": "FeatureCollection", "features": features})


# ---------------------------------------------------------------------------
# GET /heatmap-data
# ---------------------------------------------------------------------------

@router.get("/heatmap-data")
async def get_heatmap_data() -> JSONResponse:
    state = get_app_state()
    df = state.get("df")

    if df is None:
        raise HTTPException(status_code=400, detail=_NO_DATA_DETAIL)

    # Support both column naming conventions
    import pandas as pd
    if "lat" in df.columns and "lon" in df.columns:
        lats = df["lat"].astype(float)
        lons = df["lon"].astype(float)
    elif "latitude" in df.columns and "longitude" in df.columns:
        lats = df["latitude"].astype(float)
        lons = df["longitude"].astype(float)
    else:
        return JSONResponse(content={"points": []})

    rounded_lats = lats.round(4)
    rounded_lons = lons.round(4)

    location_series = pd.Series(list(zip(rounded_lats, rounded_lons)))
    counts = location_series.value_counts()

    max_count = int(counts.max()) if len(counts) > 0 else 1

    points = [
        [float(lat), float(lon), float(count) / max_count]
        for (lat, lon), count in counts.items()
    ]

    if len(points) > 5000:
        step = len(points) / 5000
        points = [points[int(i * step)] for i in range(5000)]

    return JSONResponse(content={"points": points})


# ---------------------------------------------------------------------------
# GET /time-stats
# ---------------------------------------------------------------------------

@router.get("/time-stats")
async def get_time_stats() -> JSONResponse:
    """
    Return the cached temporal analysis dictionary.
    """
    state = get_app_state()
    time_stats = state.get("time_stats")

    if time_stats is None:
        raise HTTPException(status_code=400, detail=_NO_DATA_DETAIL)

    return JSONResponse(content=time_stats)


# ---------------------------------------------------------------------------
# GET /top-junctions
# ---------------------------------------------------------------------------

@router.get("/top-junctions")
async def get_top_junctions() -> JSONResponse:
    """
    Return the top 10 junctions extracted from the cached temporal stats.
    """
    state = get_app_state()
    time_stats = state.get("time_stats")

    if time_stats is None:
        raise HTTPException(status_code=400, detail=_NO_DATA_DETAIL)

    return JSONResponse(content={"junctions": time_stats.get("top_junctions", [])})
