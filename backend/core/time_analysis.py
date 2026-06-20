"""
core/time_analysis.py — Temporal pattern analysis for ParkIQ.

Provides:
    compute_temporal_stats(df)  — builds a JSON-serializable summary dict
    _to_native(val)             — recursively converts numpy scalars/arrays to
                                  Python native types for safe json.dumps()
"""

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Days-of-week in calendar order (Monday-first, ISO convention)
# ---------------------------------------------------------------------------
_DAY_ORDER = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
]

# ---------------------------------------------------------------------------
# Resolution time bucket boundaries (in minutes)
# ---------------------------------------------------------------------------
_RESOLUTION_BUCKETS = {
    "<30min":    lambda m: m < 30,
    "30-60min":  lambda m: 30 <= m < 60,
    "1-2hrs":    lambda m: 60 <= m < 120,
    "2-6hrs":    lambda m: 120 <= m < 360,
    ">6hrs":     lambda m: m >= 360,
}


# ---------------------------------------------------------------------------
# Public helper: convert numpy / pandas scalars to Python-native types
# ---------------------------------------------------------------------------

def _to_native(val):
    """
    Recursively convert numpy/pandas scalar and array types to Python-native
    counterparts so the result is safe to pass through json.dumps().

    Handles:
        - numpy integer types   → int
        - numpy floating types  → float
        - numpy bool_           → bool
        - numpy ndarray         → list (elements recursively converted)
        - pandas NA / NaT / NaN → None
        - dict / list           → recurse into values/items
        - everything else       → returned unchanged (assumed already native)
    """
    # --- numpy integer scalars ---
    if isinstance(val, (np.integer,)):
        return int(val)

    # --- numpy floating scalars ---
    if isinstance(val, (np.floating,)):
        f = float(val)
        # NaN and Inf are not valid JSON; map to None
        return None if (f != f or f == float("inf") or f == float("-inf")) else f

    # --- numpy bool ---
    if isinstance(val, (np.bool_,)):
        return bool(val)

    # --- numpy arrays ---
    if isinstance(val, np.ndarray):
        return [_to_native(v) for v in val.tolist()]

    # --- pandas NA types (pd.NA, pd.NaT) ---
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass  # isna() can raise for non-scalar containers — handled below

    # --- Python float NaN / Inf ---
    if isinstance(val, float):
        if val != val or val == float("inf") or val == float("-inf"):
            return None

    # --- dict ---
    if isinstance(val, dict):
        return {k: _to_native(v) for k, v in val.items()}

    # --- list / tuple ---
    if isinstance(val, (list, tuple)):
        return [_to_native(v) for v in val]

    return val


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def compute_temporal_stats(df: pd.DataFrame) -> dict:
    """
    Derive temporal and categorical statistics from a cleaned violations DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        Cleaned DataFrame produced by loader.load_and_clean() or
        loader.generate_synthetic_data().  All columns are optional — missing
        columns are handled gracefully and filled with zeros / empty lists.

    Returns
    -------
    dict
        A JSON-serializable dict with the following keys:

        hourly : dict[str, int]
            Violation counts for each hour of the day (keys "0"–"23").
            Missing hours are filled with 0.

        day_of_week : dict[str, int]
            Violation counts keyed by day name (Monday–Sunday).
            Missing days are filled with 0.

        weekly_trend : list[dict]
            [{"week": <int>, "count": <int>}, ...] sorted ascending by week.
            NaN week entries are excluded.

        top_junctions : list[dict]
            Up to 10 junctions with highest violation counts.
            Each entry: {"junction_name": str, "count": int,
                         "lat": float, "lon": float}
            Returns [] if the junction_name column is absent.

        vehicle_types : list[dict]
            [{"vehicle_type": str, "count": int, "percentage": float}, ...]
            Percentage = (count / total_records) * 100, rounded to 1 decimal.
            Returns [] if column absent.

        violation_types : list[dict]
            [{"violation_type": str, "count": int}, ...] sorted by count desc.
            Returns [] if column absent.

        resolution_buckets : dict[str, int]
            {"<30min": int, "30-60min": int, "1-2hrs": int,
             "2-6hrs": int, ">6hrs": int}
            Based on resolution_minutes; NaN and negative values are skipped.
            Returns all-zeros if column absent.
    """

    # --- 1. hourly -----------------------------------------------------------
    hourly: dict[str, int] = {str(h): 0 for h in range(24)}
    if "hour_of_day" in df.columns:
        counts = (
            df["hour_of_day"]
            .dropna()
            .astype(int)
            .value_counts()
        )
        for hour, count in counts.items():
            key = str(int(hour))
            if key in hourly:
                hourly[key] = int(count)

    # --- 2. day_of_week -------------------------------------------------------
    day_of_week: dict[str, int] = {d: 0 for d in _DAY_ORDER}
    if "day_of_week" in df.columns:
        counts = df["day_of_week"].dropna().value_counts()
        for day, count in counts.items():
            if day in day_of_week:
                day_of_week[day] = int(count)

    # --- 3. weekly_trend ------------------------------------------------------
    weekly_trend: list[dict] = []
    if "week_number" in df.columns:
        valid_weeks = df["week_number"].dropna()
        if len(valid_weeks) > 0:
            # week_number may be pandas Int64 (nullable); cast to plain int64
            week_counts = (
                valid_weeks
                .astype("int64")
                .value_counts()
                .sort_index()
            )
            for week_num, count in week_counts.items():
                weekly_trend.append({
                    "week": int(week_num),
                    "count": int(count),
                })

    # --- 4. top_junctions -----------------------------------------------------
    top_junctions: list[dict] = []
    if "junction_name" in df.columns:
        # We need lat/lon columns to attach coordinates
        has_lat = "latitude" in df.columns
        has_lon = "longitude" in df.columns

        # Build a grouped table: count + mean lat/lon per junction
        agg_cols: dict[str, object] = {"junction_name": "count"}
        agg_map: dict = {}

        # Use a helper sub-df to avoid KeyError when lat/lon absent
        sub = df[["junction_name"]].copy()
        if has_lat:
            sub["latitude"] = df["latitude"]
        if has_lon:
            sub["longitude"] = df["longitude"]

        sub = sub[sub["junction_name"].notna()]

        if len(sub) > 0:
            group_cols = ["junction_name"]
            # Aggregate: count rows, mean lat/lon
            grp = sub.groupby("junction_name", sort=False)
            result = grp.size().rename("count").reset_index()

            if has_lat:
                result = result.merge(
                    grp["latitude"].mean().rename("lat").reset_index(),
                    on="junction_name",
                    how="left",
                )
            else:
                result["lat"] = 0.0

            if has_lon:
                result = result.merge(
                    grp["longitude"].mean().rename("lon").reset_index(),
                    on="junction_name",
                    how="left",
                )
            else:
                result["lon"] = 0.0

            # Top 10 by count
            result = result.nlargest(10, "count")

            for _, row in result.iterrows():
                top_junctions.append({
                    "junction_name": str(row["junction_name"]),
                    "count": int(row["count"]),
                    "lat": _to_native(row["lat"]),
                    "lon": _to_native(row["lon"]),
                })

    # --- 5. vehicle_types -----------------------------------------------------
    vehicle_types: list[dict] = []
    if "vehicle_type" in df.columns:
        total = max(len(df), 1)  # avoid division by zero
        counts = df["vehicle_type"].dropna().value_counts()
        for vtype, count in counts.items():
            vehicle_types.append({
                "vehicle_type": str(vtype),
                "count": int(count),
                "percentage": round(float(count) / total * 100, 1),
            })

    # --- 6. violation_types ---------------------------------------------------
    violation_types: list[dict] = []
    if "violation_type" in df.columns:
        counts = (
            df["violation_type"]
            .dropna()
            .value_counts()
            .sort_values(ascending=False)
        )
        for vtype, count in counts.items():
            violation_types.append({
                "violation_type": str(vtype),
                "count": int(count),
            })

    # --- 7. resolution_buckets ------------------------------------------------
    resolution_buckets: dict[str, int] = {k: 0 for k in _RESOLUTION_BUCKETS}
    if "resolution_minutes" in df.columns:
        valid_minutes = (
            df["resolution_minutes"]
            .dropna()                           # drop NaN
            .pipe(lambda s: s[s >= 0])          # drop negatives
        )
        for minutes in valid_minutes:
            for bucket_name, predicate in _RESOLUTION_BUCKETS.items():
                if predicate(float(minutes)):
                    resolution_buckets[bucket_name] += 1
                    break  # each value belongs to exactly one bucket

    # --- Assemble and deep-convert -------------------------------------------
    result = {
        "hourly": hourly,
        "day_of_week": day_of_week,
        "weekly_trend": weekly_trend,
        "top_junctions": top_junctions,
        "vehicle_types": vehicle_types,
        "violation_types": violation_types,
        "resolution_buckets": resolution_buckets,
    }

    return _to_native(result)
