"""
preprocess_dataset.py — One-time script to pre-process the 112MB CSV into a
compact precomputed_data.json that the backend loads instantly at startup.

Run from the parkiq/backend directory:
    python preprocess_dataset.py

This avoids shipping the 112MB CSV to Render and avoids OOM during startup.
"""

import json
import re
import sys
from collections import Counter
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN


CSV_PATH = "/Users/sachin/Sachin/Achiever/Projects/Flipkart_Grid/jan to may police violation_anonymized791b166.csv"
OUT_PATH  = "data/precomputed_data.json"

PEAK_HOURS = {7, 8, 9, 17, 18, 19, 20}


def parse_violation_type(val: str) -> str:
    """Extract first element from JSON-array-style violation_type strings."""
    if not val or val in ("nan", "NULL", ""):
        return "Unknown"
    s = str(val).strip()
    if s.startswith("["):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list) and parsed:
                return str(parsed[0]).title()
        except Exception:
            m = re.search(r'"([^"]+)"', s)
            if m:
                return m.group(1).title()
    return s.title()


def main():
    print(f"Reading CSV: {CSV_PATH}", flush=True)
    df = pd.read_csv(CSV_PATH, dtype=str, keep_default_na=False)
    df = df.replace("", pd.NA)

    print(f"  Raw rows: {len(df):,}", flush=True)

    # ── 1. Filter: only approved/valid rows with valid coords ───────────────
    if "validation_status" in df.columns:
        df = df[df["validation_status"].str.lower().isin(["approved", "valid"])]
    print(f"  After approval filter: {len(df):,}", flush=True)

    df = df.assign(
        lat=pd.to_numeric(df["latitude"],  errors="coerce"),
        lon=pd.to_numeric(df["longitude"], errors="coerce"),
    )
    df = df.dropna(subset=["lat", "lon"])
    df = df[(df["lat"] != 0) & (df["lon"] != 0)]
    print(f"  After coord filter: {len(df):,}", flush=True)

    # ── 2. Parse datetimes ──────────────────────────────────────────────────
    print("  Parsing datetimes (vectorized)...", flush=True)
    df["created_dt"] = pd.to_datetime(df["created_datetime"], utc=True, errors="coerce").dt.tz_convert(None)
    df["closed_dt"]  = pd.to_datetime(df["closed_datetime"],  utc=True, errors="coerce").dt.tz_convert(None)
    df = df.dropna(subset=["created_dt"])

    df = df.assign(
        hour        = df["created_dt"].dt.hour,
        day_of_week = df["created_dt"].dt.day_name(),
        week        = df["created_dt"].dt.isocalendar().week.astype(int),
        month       = df["created_dt"].dt.month,
        res_min     = (df["closed_dt"] - df["created_dt"]).dt.total_seconds() / 60,
    )
    df = df.assign(is_peak = df["hour"].isin(PEAK_HOURS))

    # ── 3. Normalize violation_type ─────────────────────────────────────────
    df["vtype"] = df["violation_type"].apply(parse_violation_type)

    # ── 4. DBSCAN clustering on lat/lon ─────────────────────────────────────
    print("  Running DBSCAN clustering...", flush=True)
    coords_rad = np.radians(df[["lat", "lon"]].values.astype(float))
    db = DBSCAN(
        eps=np.radians(0.001),   # ~111 metres
        min_samples=8,
        algorithm="ball_tree",
        metric="haversine",
    )
    df = df.assign(cluster=db.fit_predict(coords_rad))

    # ── 5. Build cluster summaries ──────────────────────────────────────────
    print("  Building cluster summaries...", flush=True)
    clustered = df[df["cluster"] >= 0].copy()
    cluster_rows = []
    for cid, grp in clustered.groupby("cluster"):
        junctions = [j for j in grp["junction_name"].dropna().tolist()
                     if str(j) not in ("No Junction", "nan", "NULL", "")]
        vt_list = grp["vtype"].tolist()
        dom_vt  = Counter(vt_list).most_common(1)[0][0] if vt_list else "Unknown"

        rm_vals = grp["res_min"].dropna()
        rm_vals = rm_vals[rm_vals.between(0, 10000)]

        cluster_rows.append({
            "cluster_id": int(cid),
            "centroid_lat": float(grp["lat"].mean()),
            "centroid_lon": float(grp["lon"].mean()),
            "violation_count": int(len(grp)),
            "dominant_violation_type": dom_vt,
            "peak_hour_ratio": float(grp["is_peak"].mean()),
            "avg_resolution_minutes": float(rm_vals.mean()) if len(rm_vals) else 0.0,
            "unique_vehicle_types": int(grp["vehicle_type"].dropna().nunique()),
            "junctions_covered": list(set(junctions))[:6],
            "police_stations_involved": list(grp["police_station"].dropna().unique())[:4],
            "first_seen": str(grp["created_dt"].min()),
            "last_seen":  str(grp["created_dt"].max()),
        })

    clusters_df = pd.DataFrame(cluster_rows).sort_values("violation_count", ascending=False)
    print(f"  Clusters found: {len(clusters_df)}", flush=True)

    # ── 6. Impact scoring ───────────────────────────────────────────────────
    def compute_impact(row):
        score = 0
        vc = row["violation_count"]
        if vc > 500: score += 40
        elif vc > 200: score += 30
        elif vc > 100: score += 20
        else: score += 10
        score += row["peak_hour_ratio"] * 30
        rm = row["avg_resolution_minutes"]
        if rm > 120: score += 20
        elif rm > 60: score += 15
        elif rm > 30: score += 10
        else: score += 5
        score += min(row["unique_vehicle_types"] * 2, 10)
        return min(round(score, 1), 100.0)

    def tier(score):
        if score >= 75: return "Critical"
        if score >= 55: return "High"
        if score >= 35: return "Medium"
        return "Low"

    clusters_df["impact_score"] = clusters_df.apply(compute_impact, axis=1)
    clusters_df["priority_tier"] = clusters_df["impact_score"].apply(tier)
    clusters_df["recommended_enforcement_time"] = clusters_df["peak_hour_ratio"].apply(
        lambda r: "7-9 AM and 5-8 PM" if r > 0.5 else "10 AM - 4 PM"
    )

    # ── 7. Time stats ───────────────────────────────────────────────────────
    print("  Computing time stats...", flush=True)
    hourly = df["hour"].value_counts().sort_index().to_dict()
    hourly = {str(k): int(v) for k, v in hourly.items()}

    dow    = df["day_of_week"].value_counts().to_dict()
    dow    = {k: int(v) for k, v in dow.items()}

    weekly = df.groupby("week").size().reset_index(name="count")
    weekly_list = [{"week": int(r["week"]), "count": int(r["count"])}
                   for _, r in weekly.iterrows()]

    top_junctions = (
        df[df["junction_name"].notna()
           & ~df["junction_name"].isin(["No Junction", "nan", "NULL"])]
        ["junction_name"].value_counts().head(15)
    )
    top_j_list = [{"junction_name": k, "count": int(v)}
                  for k, v in top_junctions.items()]

    vt_counts = df["vtype"].value_counts().head(10)
    vt_list_out = [{"violation_type": k, "count": int(v)}
                   for k, v in vt_counts.items()]

    vehicle_types = df["vehicle_type"].value_counts().head(8)
    veh_list = [{"type": k, "count": int(v)} for k, v in vehicle_types.items()]

    # Resolution bucket distribution
    rm_valid = df["res_min"].dropna()
    rm_valid = rm_valid[rm_valid.between(0, 1440)]
    res_buckets = {
        "0-30 min":  int((rm_valid <= 30).sum()),
        "30-60 min": int(((rm_valid > 30) & (rm_valid <= 60)).sum()),
        "1-2 hrs":   int(((rm_valid > 60) & (rm_valid <= 120)).sum()),
        "2-4 hrs":   int(((rm_valid > 120) & (rm_valid <= 240)).sum()),
        "4+ hrs":    int((rm_valid > 240).sum()),
    }

    # ── 8. Map points — sample 3000 points for frontend heatmap ─────────────
    sample_size = min(3000, len(df))
    map_sample = df.sample(sample_size, random_state=42)[["lat", "lon", "vtype", "hour", "junction_name"]].copy()
    map_sample["junction_name"] = map_sample["junction_name"].fillna("").astype(str).replace("No Junction", "")
    map_points = [
        {
            "latitude":       round(float(r["lat"]), 6),
            "longitude":      round(float(r["lon"]), 6),
            "violation_type": str(r["vtype"]),
            "hour":           int(r["hour"]),
            "junction_name":  str(r["junction_name"]),
        }
        for _, r in map_sample.iterrows()
    ]

    # ── 9. Dashboard summary ────────────────────────────────────────────────
    rm_all = df["res_min"].dropna()
    rm_all = rm_all[rm_all.between(0, 10000)]

    dashboard = {
        "total_violations": int(len(df)),
        "active_clusters":  int(len(clusters_df)),
        "critical_zones":   int((clusters_df["priority_tier"] == "Critical").sum()),
        "avg_resolution_minutes": round(float(rm_all.mean()), 1) if len(rm_all) else 0.0,
        "last_updated": datetime.utcnow().isoformat(),
    }

    # ── 10. Assemble and write JSON ─────────────────────────────────────────
    out = {
        "dashboard": dashboard,
        "clusters": clusters_df.to_dict(orient="records"),
        "time_stats": {
            "hourly": hourly,
            "day_of_week": dow,
            "weekly_trend": weekly_list,
            "top_junctions": top_j_list,
            "violation_types": vt_list_out,
            "vehicle_types": veh_list,
            "resolution_buckets": res_buckets,
        },
        "map_points": map_points,
    }

    import os
    os.makedirs("data", exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, default=str, separators=(",", ":"))

    size_kb = os.path.getsize(OUT_PATH) / 1024
    print(f"\n✅ Done! Written to {OUT_PATH} ({size_kb:.1f} KB)", flush=True)
    print(f"   Total violations : {dashboard['total_violations']:,}")
    print(f"   Clusters         : {dashboard['active_clusters']}")
    print(f"   Critical zones   : {dashboard['critical_zones']}")
    print(f"   Avg resolution   : {dashboard['avg_resolution_minutes']} min")


if __name__ == "__main__":
    main()
