"""
core/clustering.py — DBSCAN hotspot detection for ParkIQ.

Provides:
    run_dbscan(df, eps, min_samples) -> pd.DataFrame
        Runs DBSCAN on lat/lon data and returns df with a `cluster_label` column.

    get_cluster_summaries(df, labels) -> pd.DataFrame
        Aggregates per-cluster statistics from a labelled DataFrame.

    run_clustering(df) -> tuple[pd.DataFrame, pd.DataFrame]
        Convenience wrapper: calls run_dbscan then get_cluster_summaries.
"""

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN


# ---------------------------------------------------------------------------
# DBSCAN runner
# ---------------------------------------------------------------------------

def run_dbscan(
    df: pd.DataFrame,
    eps: float = 0.0008,
    min_samples: int = 5,
) -> pd.DataFrame:
    """
    Run DBSCAN spatial clustering on latitude/longitude columns.

    The eps parameter is treated as degrees of arc; it is converted to radians
    (eps * π/180) before being passed to DBSCAN which uses the haversine metric
    (input in radians, output in radians).  0.0008° ≈ 89 metres.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain ``latitude`` and ``longitude`` columns.
    eps : float
        Neighbourhood radius in degrees (~km-scale).  Default 0.0008 (≈89 m).
    min_samples : int
        Minimum cluster size.  Default 5.

    Returns
    -------
    pd.DataFrame
        Copy of ``df`` with an added integer ``cluster_label`` column.
        Noise points receive label -1.
    """
    # 1. Extract lat/lon as a (N, 2) numpy array
    coords = df[["latitude", "longitude"]].values.astype(float)

    # 2. Convert degrees → radians (haversine metric expects radians)
    coords_rad = np.radians(coords)

    # 3. Convert eps from degrees to radians for haversine distance
    eps_rad = np.radians(eps)

    # 4. Run DBSCAN
    db = DBSCAN(
        eps=eps_rad,
        min_samples=min_samples,
        algorithm="ball_tree",
        metric="haversine",
    )
    labels = db.fit_predict(coords_rad)

    # 5. Attach labels to a copy of the DataFrame
    df_out = df.copy()
    df_out["cluster_label"] = labels.astype(int)

    return df_out


# ---------------------------------------------------------------------------
# Cluster summary builder
# ---------------------------------------------------------------------------

def get_cluster_summaries(df: pd.DataFrame, labels: np.ndarray) -> pd.DataFrame:
    """
    Build a summary DataFrame with one row per real cluster (label != -1).

    Avoids all boolean-mask DataFrame filtering (which triggers a Python 3.14
    + pandas 2.2.x checknull segfault on large mixed-NA DataFrames).
    Uses integer-index grouping via numpy instead.
    """
    labels = np.asarray(labels, dtype=np.int32)
    unique_labels = [l for l in np.unique(labels) if l != -1]

    if len(unique_labels) == 0:
        return pd.DataFrame(columns=[
            "cluster_id", "centroid_lat", "centroid_lon", "violation_count",
            "unique_vehicle_types", "dominant_violation_type", "peak_hour_ratio",
            "avg_resolution_minutes", "junctions_covered", "police_stations_involved",
            "first_seen", "last_seen",
        ])

    # Pre-extract columns we need as plain numpy arrays / Python lists
    # to avoid touching the DataFrame internals during per-cluster iteration
    lats = df["latitude"].to_numpy(dtype=float, na_value=np.nan)
    lons = df["longitude"].to_numpy(dtype=float, na_value=np.nan)

    veh_types   = df["vehicle_type"].tolist()   if "vehicle_type"   in df.columns else None
    viol_types  = df["violation_type"].tolist()  if "violation_type"  in df.columns else None
    peak_hours  = df["is_peak_hour"].tolist()    if "is_peak_hour"    in df.columns else None
    res_mins    = df["resolution_minutes"].tolist() if "resolution_minutes" in df.columns else None
    junctions   = df["junction_name"].tolist()   if "junction_name"   in df.columns else None
    stations    = df["police_station"].tolist()  if "police_station"  in df.columns else None
    created_dts = df["created_datetime"].astype(object).tolist() if "created_datetime" in df.columns else None

    # Build index lists per label using numpy (no pandas boolean indexing)
    label_to_indices: dict[int, list[int]] = {int(l): [] for l in unique_labels}
    for idx, lbl in enumerate(labels.tolist()):
        if lbl in label_to_indices:
            label_to_indices[lbl].append(idx)

    rows = []
    for label in unique_labels:
        idxs = label_to_indices[int(label)]
        if not idxs:
            continue

        # Geometry
        c_lats = [lats[i] for i in idxs if not np.isnan(lats[i])]
        c_lons = [lons[i] for i in idxs if not np.isnan(lons[i])]
        centroid_lat = float(np.mean(c_lats)) if c_lats else 0.0
        centroid_lon = float(np.mean(c_lons)) if c_lons else 0.0
        violation_count = len(idxs)

        # Vehicle types
        if veh_types is not None:
            vt_vals = {str(veh_types[i]) for i in idxs
                       if veh_types[i] is not None and str(veh_types[i]) not in ("nan", "None", "")}
            unique_vehicle_types = len(vt_vals)
        else:
            unique_vehicle_types = 0

        # Dominant violation type
        if viol_types is not None:
            vt_list = [str(viol_types[i]) for i in idxs
                       if viol_types[i] is not None and str(viol_types[i]) not in ("nan", "None", "")]
            if vt_list:
                from collections import Counter
                dominant_violation_type = Counter(vt_list).most_common(1)[0][0]
            else:
                dominant_violation_type = "Unknown"
        else:
            dominant_violation_type = "Unknown"

        # Peak hour ratio
        if peak_hours is not None:
            ph_vals = [peak_hours[i] for i in idxs if peak_hours[i] is not None]
            peak_hour_ratio = float(sum(bool(v) for v in ph_vals) / len(ph_vals)) if ph_vals else 0.0
        else:
            peak_hour_ratio = 0.0

        # Avg resolution minutes
        if res_mins is not None:
            rm_vals = []
            for i in idxs:
                v = res_mins[i]
                try:
                    fv = float(v)
                    if not (np.isnan(fv) or np.isinf(fv)) and fv >= 0:
                        rm_vals.append(fv)
                except (TypeError, ValueError):
                    pass
            avg_resolution_minutes = float(np.mean(rm_vals)) if rm_vals else 0.0
        else:
            avg_resolution_minutes = 0.0

        # Junctions covered
        if junctions is not None:
            j_vals = list({str(junctions[i]) for i in idxs
                           if junctions[i] is not None and str(junctions[i]) not in ("nan", "None", "")})
        else:
            j_vals = []

        # Police stations
        if stations is not None:
            s_vals = list({str(stations[i]) for i in idxs
                           if stations[i] is not None and str(stations[i]) not in ("nan", "None", "")})
        else:
            s_vals = []

        # Temporal bounds
        if created_dts is not None:
            dt_strs = [str(created_dts[i]) for i in idxs
                       if created_dts[i] is not None
                       and str(created_dts[i]) not in ("", "NaT", "nan", "None")]
            first_seen = min(dt_strs) if dt_strs else None
            last_seen  = max(dt_strs) if dt_strs else None
        else:
            first_seen = last_seen = None

        rows.append({
            "cluster_id": int(label),
            "centroid_lat": centroid_lat,
            "centroid_lon": centroid_lon,
            "violation_count": violation_count,
            "unique_vehicle_types": unique_vehicle_types,
            "dominant_violation_type": dominant_violation_type,
            "peak_hour_ratio": peak_hour_ratio,
            "avg_resolution_minutes": avg_resolution_minutes,
            "junctions_covered": j_vals,
            "police_stations_involved": s_vals,
            "first_seen": first_seen,
            "last_seen": last_seen,
        })

    summaries = pd.DataFrame(rows)
    return summaries.sort_values("violation_count", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------

def run_clustering(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Run the full clustering pipeline in one call.

    Parameters
    ----------
    df : pd.DataFrame
        Cleaned violations DataFrame (output of ``load_and_clean`` or
        ``generate_synthetic_data``).

    Returns
    -------
    df_with_labels : pd.DataFrame
        Original DataFrame enriched with a ``cluster_label`` column.
    cluster_summaries : pd.DataFrame
        Per-cluster summary statistics sorted by ``violation_count`` descending.
    """
    df_with_labels = run_dbscan(df)
    labels = df_with_labels["cluster_label"].values
    cluster_summaries = get_cluster_summaries(df_with_labels, labels)
    return df_with_labels, cluster_summaries
