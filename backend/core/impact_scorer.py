"""
core/impact_scorer.py — Congestion impact scoring for ParkIQ.

Provides:
    compute_impact_scores(cluster_df: pd.DataFrame) -> pd.DataFrame
        Enriches a cluster summary DataFrame (output of get_cluster_summaries)
        with impact scores, priority tiers, colors, and enforcement time windows.
"""

import ast

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize(series: pd.Series) -> pd.Series:
    """
    Min-max normalise a numeric Series to [0, 1].

    If all values are identical (or the series has a single element) the
    denominator would be zero, so every element is set to 0.5 instead.
    """
    min_val = series.min()
    max_val = series.max()
    if min_val == max_val:
        return pd.Series([0.5] * len(series), index=series.index, dtype=float)
    return (series - min_val) / (max_val - min_val)


def _parse_junctions(value) -> int:
    """
    Return the number of junctions in *value*.

    *value* may be:
    - A Python list  → use len() directly.
    - A string repr of a list (e.g. "['A', 'B']") → parse with ast.literal_eval.
    - Any other type → 0.
    """
    if isinstance(value, list):
        return len(value)
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("["):
            try:
                parsed = ast.literal_eval(value)
                if isinstance(parsed, list):
                    return len(parsed)
            except (ValueError, SyntaxError):
                pass
        # Non-list string — treat as a single junction name if non-empty
        return 1 if value else 0
    return 0


def _recommended_enforcement_time(peak_hour_ratio: float) -> str:
    """
    Return a human-readable patrol-time recommendation based on peak_hour_ratio.
    """
    if peak_hour_ratio >= 0.5:
        return "Morning & Evening Rush Hours (7-9 AM, 5-8 PM)"
    if peak_hour_ratio >= 0.3:
        return "Evening Rush Hours (5-8 PM)"
    return "Business Hours (10 AM - 4 PM)"


def _priority_tier(score: float) -> str:
    if score >= 75:
        return "Critical"
    if score >= 50:
        return "High"
    if score >= 25:
        return "Medium"
    return "Low"


_PRIORITY_COLOR = {
    "Critical": "#ef4444",
    "High":     "#f97316",
    "Medium":   "#eab308",
    "Low":      "#22c55e",
}

_EMPTY_COLUMNS = [
    "impact_score",
    "priority_tier",
    "priority_color",
    "recommended_enforcement_time",
]

_EPSILON = 1e-6  # replacement for zero avg_resolution_minutes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_impact_scores(cluster_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute congestion impact scores for each cluster.

    Parameters
    ----------
    cluster_df : pd.DataFrame
        Output of ``get_cluster_summaries()``.  Expected columns:
        cluster_id, centroid_lat, centroid_lon, violation_count,
        unique_vehicle_types, dominant_violation_type, peak_hour_ratio,
        avg_resolution_minutes, junctions_covered, police_stations_involved,
        first_seen, last_seen.

    Returns
    -------
    pd.DataFrame
        The input DataFrame enriched with:
        - ``impact_score``                (float, 0–100)
        - ``priority_tier``              (str: Critical / High / Medium / Low)
        - ``priority_color``             (str: hex colour code)
        - ``recommended_enforcement_time`` (str)
        Still sorted by ``violation_count`` descending (preserves original order).

    Edge cases
    ----------
    - Empty DataFrame  → returned unchanged with the four new columns added
                         (all values will be NaN / None).
    - Single-row DF    → normalization returns 0.5 for every component,
                         yielding a score of 50.0 (clipped to [0, 100]).
    - Zero resolution  → replaced by epsilon (1e-6) before inversion.
    """
    df = cluster_df.copy()

    # -- 1. Empty DataFrame ---------------------------------------------------
    if df.empty:
        for col in _EMPTY_COLUMNS:
            df = df.assign(**{col: pd.Series(dtype=object)})
        return df

    # -- 2. Junction density score --------------------------------------------
    junction_density = df["junctions_covered"].apply(_parse_junctions)

    # -- 3. Inverted resolution -----------------------------------------------
    resolution = df["avg_resolution_minutes"].astype(float).copy()
    resolution = resolution.where(resolution != 0, _EPSILON)
    resolution = resolution.where(resolution.notna(), _EPSILON)
    inv_resolution = 1.0 / resolution

    # -- 4. Weighted impact score ---------------------------------------------
    norm_violation   = _normalize(df["violation_count"].astype(float))
    norm_peak        = _normalize(df["peak_hour_ratio"].astype(float))
    norm_inv_res     = _normalize(inv_resolution)
    norm_vehicle     = _normalize(df["unique_vehicle_types"].astype(float))
    norm_junction    = _normalize(junction_density.astype(float))

    raw_score = (
        0.35 * norm_violation
        + 0.25 * norm_peak
        + 0.20 * norm_inv_res
        + 0.10 * norm_vehicle
        + 0.10 * norm_junction
    ) * 100

    # -- 5. Clip to [0, 100] --------------------------------------------------
    impact_score = raw_score.clip(0, 100)

    # -- 6. Assign derived columns (Python-native values) ---------------------
    impact_score_list   = [round(float(v), 4) for v in impact_score]
    priority_tier_list  = [_priority_tier(v) for v in impact_score_list]
    priority_color_list = [_PRIORITY_COLOR[t] for t in priority_tier_list]
    enforcement_list    = [
        _recommended_enforcement_time(float(r))
        for r in df["peak_hour_ratio"]
    ]

    df = df.assign(
        impact_score=impact_score_list,
        priority_tier=priority_tier_list,
        priority_color=priority_color_list,
        recommended_enforcement_time=enforcement_list,
    )

    return df
