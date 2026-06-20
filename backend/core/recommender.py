"""
core/recommender.py — Grok AI enforcement recommendations for ParkIQ.

Provides:
    generate_enforcement_recommendations(
        clusters_df: pd.DataFrame,
        top_n: int = 5
    ) -> list[dict]

        Takes the output of compute_impact_scores(), selects the top-N
        clusters by impact_score, and returns AI-generated enforcement
        recommendations for each.  Falls back to structured mock
        recommendations when the XAI_API_KEY environment variable is
        not set or when the API call / JSON parsing fails.

Uses the xAI Grok API (OpenAI-compatible) via the openai Python SDK.
"""

import json
import os
import re

import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are an expert traffic enforcement analyst for an Indian metro city.\n"
    "You will receive data about parking violation hotspots detected by an AI "
    "clustering system.\n"
    "For each hotspot, provide:\n"
    "1. A clear, jargon-free 2-sentence description of the problem\n"
    "2. The best time window to deploy enforcement (based on peak hour data)\n"
    "3. The most effective enforcement action type\n"
    "4. Estimated % reduction in congestion if this hotspot is addressed\n"
    "Be specific, practical, and concise. Format your response as JSON."
)

# Five varied mock entries so that calls with top_n up to 5 all get distinct
# recommendations; for larger top_n values the list cycles.
_MOCK_POOL = [
    {
        "description": (
            "This area shows a high concentration of parking violations that "
            "regularly obstruct traffic flow. Vehicles are frequently parked "
            "in no-parking zones, causing significant congestion during peak hours."
        ),
        "patrol_time_window": "7-9 AM and 5-8 PM on weekdays",
        "enforcement_action": "Penalty notice blitz with tow truck on standby",
        "estimated_congestion_reduction": "25-35%",
        "mock": True,
        "note": "AI features require XAI_API_KEY environment variable to be set.",
    },
    {
        "description": (
            "Illegal parking near commercial establishments creates recurring "
            "bottlenecks throughout the day. The high volume of mixed vehicle "
            "types suggests this is a busy commercial corridor that needs "
            "stricter enforcement."
        ),
        "patrol_time_window": "10 AM - 1 PM and 4-7 PM daily",
        "enforcement_action": "Tow truck deployment for repeat offenders",
        "estimated_congestion_reduction": "20-30%",
        "mock": True,
        "note": "AI features require XAI_API_KEY environment variable to be set.",
    },
    {
        "description": (
            "Persistent double-parking and footpath encroachment are the "
            "dominant violation patterns here. These violations slow emergency "
            "vehicle access and force pedestrians onto the road."
        ),
        "patrol_time_window": "8-10 AM on weekdays",
        "enforcement_action": "Challan drive with traffic warden deployment",
        "estimated_congestion_reduction": "15-25%",
        "mock": True,
        "note": "AI features require XAI_API_KEY environment variable to be set.",
    },
    {
        "description": (
            "This hotspot is characterised by vehicles blocking junction "
            "approaches during morning rush hours. Short but high-frequency "
            "violations suggest commuters stopping for quick errands."
        ),
        "patrol_time_window": "7-9 AM and 6-8 PM weekdays",
        "enforcement_action": "Visible police presence + instant challan",
        "estimated_congestion_reduction": "30-40%",
        "mock": True,
        "note": "AI features require XAI_API_KEY environment variable to be set.",
    },
    {
        "description": (
            "Late-evening parking violations dominate this zone, mostly near "
            "restaurants and entertainment venues. Vehicles parked on service "
            "roads reduce lane capacity significantly after sunset."
        ),
        "patrol_time_window": "7-11 PM on weekends",
        "enforcement_action": "Night patrol with penalty notice blitz",
        "estimated_congestion_reduction": "20-28%",
        "mock": True,
        "note": "AI features require XAI_API_KEY environment variable to be set.",
    },
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_cluster_summary(row: pd.Series) -> dict:
    """
    Extract a compact, JSON-serialisable summary for a single cluster row.

    Only the fields most relevant for generating enforcement recommendations
    are included; raw geometry / color codes are omitted to keep the prompt
    concise.
    """
    def _native(val):
        """Convert numpy scalars to Python native types."""
        if hasattr(val, "item"):
            return val.item()
        return val

    return {
        "cluster_id": int(_native(row["cluster_id"])),
        "violation_count": int(_native(row["violation_count"])),
        "dominant_violation_type": str(row["dominant_violation_type"]),
        "peak_hour_ratio": round(float(_native(row["peak_hour_ratio"])), 4),
        "avg_resolution_minutes": round(float(_native(row["avg_resolution_minutes"])), 2),
        "unique_vehicle_types": int(_native(row["unique_vehicle_types"])),
        "impact_score": round(float(_native(row["impact_score"])), 2),
        "priority_tier": str(row["priority_tier"]),
        "recommended_enforcement_time": str(row["recommended_enforcement_time"]),
        "junctions_covered": (
            row["junctions_covered"]
            if isinstance(row["junctions_covered"], list)
            else []
        ),
    }


def _build_row_dict(row: pd.Series) -> dict:
    """
    Convert a cluster DataFrame row into a plain Python dict, handling numpy
    scalar types so the result is JSON-serialisable.
    """
    def _native(val):
        if hasattr(val, "item"):
            return val.item()
        if isinstance(val, list):
            return val
        return val

    return {col: _native(row[col]) for col in row.index}


def _extract_json_array(text: str) -> list:
    """
    Extract the first JSON array from *text*.

    Handles the common case where the model wraps the array in a
    ```json ... ``` code fence.

    Raises ``ValueError`` if no valid JSON array is found.
    """
    # Strip code fences if present
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fenced:
        text = fenced.group(1).strip()

    # Find the outermost [ ... ] block
    start = text.find("[")
    if start == -1:
        raise ValueError("No JSON array found in response.")

    depth = 0
    for i, ch in enumerate(text[start:], start=start):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])

    raise ValueError("Unterminated JSON array in response.")


def _call_grok(cluster_summaries: list[dict]) -> list[dict]:
    """
    Call the Groq API (OpenAI-compatible) and return recommendation dicts.

    Uses the openai Python SDK pointed at https://api.groq.com/openai/v1.
    API key is read from GROQ_API_KEY environment variable (keys start with gsk_).
    """
    from openai import OpenAI  # deferred import — only needed when key is set

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    n = len(cluster_summaries)
    user_message = (
        f"Analyze these {n} parking violation hotspots and provide enforcement "
        f"recommendations:\n\n"
        f"{json.dumps(cluster_summaries, indent=2)}\n\n"
        f"Return a JSON array with exactly {n} objects, one per hotspot, in the "
        f"same order. Each object must have:\n"
        f'- "cluster_id": integer\n'
        f'- "description": 2-sentence plain-English description\n'
        f'- "patrol_time_window": recommended deployment time (e.g., "8-10 AM weekdays")\n'
        f'- "enforcement_action": specific action (e.g., "Tow truck deployment", '
        f'"Penalty notice blitz")\n'
        f'- "estimated_congestion_reduction": percentage string (e.g., "20-30%")'
    )

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1",
    )
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=2048,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    )
    response_text = response.choices[0].message.content
    return _extract_json_array(response_text)


def _mock_recommendation(index: int) -> dict:
    """Return one mock recommendation (cycling through the pool)."""
    return dict(_MOCK_POOL[index % len(_MOCK_POOL)])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_enforcement_recommendations(
    clusters_df: pd.DataFrame,
    top_n: int = 5,
) -> list[dict]:
    """
    Generate AI-powered enforcement recommendations for the top-N hotspots.

    Parameters
    ----------
    clusters_df : pd.DataFrame
        Output of ``compute_impact_scores()``.  Must contain at minimum:
        cluster_id, centroid_lat, centroid_lon, violation_count,
        unique_vehicle_types, dominant_violation_type, peak_hour_ratio,
        avg_resolution_minutes, junctions_covered, police_stations_involved,
        first_seen, last_seen, impact_score, priority_tier, priority_color,
        recommended_enforcement_time.
    top_n : int
        Number of top clusters to include. If the DataFrame has fewer rows,
        all rows are used.

    Returns
    -------
    list[dict]
        One dict per cluster, combining all cluster fields with AI-generated
        fields: description, patrol_time_window, enforcement_action,
        estimated_congestion_reduction, and mock (bool).
    """
    if clusters_df.empty:
        return []

    # ------------------------------------------------------------------
    # 1. Select top-N clusters by impact_score (descending)
    # ------------------------------------------------------------------
    top_clusters = (
        clusters_df
        .sort_values("impact_score", ascending=False)
        .head(top_n)
        .reset_index(drop=True)
    )

    # ------------------------------------------------------------------
    # 2. Build compact JSON summaries for the prompt
    # ------------------------------------------------------------------
    cluster_summaries = [
        _build_cluster_summary(top_clusters.iloc[i])
        for i in range(len(top_clusters))
    ]

    # ------------------------------------------------------------------
    # 3. Attempt AI recommendations; fall back to mocks on any failure
    # ------------------------------------------------------------------
    ai_recommendations: list[dict] | None = None
    use_mock = False

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        use_mock = True
    else:
        try:
            ai_recommendations = _call_grok(cluster_summaries)
        except Exception:
            # Network error, parse error, quota exceeded, etc.
            use_mock = True

    # ------------------------------------------------------------------
    # 4. Assemble final result list
    # ------------------------------------------------------------------
    results: list[dict] = []

    for i in range(len(top_clusters)):
        row = top_clusters.iloc[i]
        base = _build_row_dict(row)

        # Merge AI or mock recommendation fields
        if use_mock or ai_recommendations is None:
            rec = _mock_recommendation(i)
        else:
            # Prefer the AI entry whose cluster_id matches; fall back to
            # positional match in case Claude reordered the array.
            target_id = int(base["cluster_id"])
            rec = next(
                (r for r in ai_recommendations if r.get("cluster_id") == target_id),
                ai_recommendations[i] if i < len(ai_recommendations) else _mock_recommendation(i),
            )
            # Ensure mock flag is present and accurate
            rec.setdefault("mock", False)

        # Overlay AI fields onto base cluster dict
        base["description"] = rec.get("description", "")
        base["patrol_time_window"] = rec.get("patrol_time_window", "")
        base["enforcement_action"] = rec.get("enforcement_action", "")
        base["estimated_congestion_reduction"] = rec.get(
            "estimated_congestion_reduction", ""
        )
        base["mock"] = bool(rec.get("mock", False))

        results.append(base)

    return results
