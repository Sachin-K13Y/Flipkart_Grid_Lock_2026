"""
api/routes_ai_insights.py — AI insights endpoints for ParkIQ.

Provides:
    GET  /api/recommendations  — Return cached AI enforcement recommendations
    POST /api/ask              — Natural language Q&A powered by Grok (xAI)
"""

import json
import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

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


class QuestionRequest(BaseModel):
    question: str


# ---------------------------------------------------------------------------
# GET /api/recommendations
# ---------------------------------------------------------------------------

@router.get("/recommendations")
def get_recommendations() -> JSONResponse:
    """
    Return the cached AI enforcement recommendations from app_state.

    Returns
    -------
    200 JSONResponse
        { "recommendations": [ ...list of recommendation dicts... ] }
        Returns an empty list if no recommendations are available yet.
    """
    state = get_app_state()

    if state["recommendations"] is None:
        return JSONResponse(content={"recommendations": []})

    return JSONResponse(content={"recommendations": state["recommendations"]})


# ---------------------------------------------------------------------------
# POST /api/ask
# ---------------------------------------------------------------------------

@router.post("/ask")
def ask_question(request: QuestionRequest) -> JSONResponse:
    """
    Answer a natural language question about the parking violation data using
    Claude claude-sonnet-4-6.

    The route builds a compact data context from the current app_state and
    passes it to Claude along with the operator's question.

    Parameters
    ----------
    request : QuestionRequest
        JSON body with a single ``question`` string field.

    Returns
    -------
    200 JSONResponse
        { "answer": "<AI-generated answer>" }
        or { "answer": "<message>", "mock": true }  when AI is unavailable.
    """
    state = get_app_state()

    # ------------------------------------------------------------------
    # 1. Guard: no data loaded yet
    # ------------------------------------------------------------------
    if state["df"] is None:
        return JSONResponse(
            content={
                "answer": "No data loaded. Please upload a CSV file first.",
                "mock": True,
            }
        )

    # ------------------------------------------------------------------
    # 2. Build a rich context dict from ALL cached state
    # ------------------------------------------------------------------
    context: dict = {
        "total_violations": int(len(state["df"])),
    }

    # Date range
    if "created_datetime" in state["df"].columns:
        dt_strings = state["df"]["created_datetime"].dropna().astype(str)
        if not dt_strings.empty:
            context["date_range"] = {"from": min(dt_strings), "to": max(dt_strings)}

    # Top-5 cluster summaries
    if state["clusters"] is not None and not state["clusters"].empty:
        top_clusters = []
        for _, row in state["clusters"].head(5).iterrows():
            top_clusters.append({
                "cluster_id": int(row["cluster_id"]),
                "violation_count": int(row["violation_count"]),
                "dominant_violation_type": str(row.get("dominant_violation_type", "")),
                "impact_score": float(row.get("impact_score", 0.0)),
                "priority_tier": str(row.get("priority_tier", "")),
                "avg_resolution_minutes": float(row.get("avg_resolution_minutes", 0.0)),
                "peak_hour_ratio": float(row.get("peak_hour_ratio", 0.0)),
                "junctions_covered": (
                    row["junctions_covered"]
                    if isinstance(row.get("junctions_covered"), list)
                    else []
                ),
            })
        context["top_clusters"] = top_clusters

    if state["time_stats"]:
        ts = state["time_stats"]

        # Hourly breakdown — find actual peak hours from data
        if ts.get("hourly"):
            hourly = ts["hourly"]
            sorted_hours = sorted(hourly.items(), key=lambda x: x[1], reverse=True)
            context["top_5_hours"] = [
                {"hour": f"{h}:00-{h}:59", "violations": c}
                for h, c in sorted_hours[:5]
            ]
            # Find the single busiest hour
            peak_h, peak_c = sorted_hours[0]
            context["peak_hour"] = f"{peak_h}:00 with {peak_c} violations"

        # Day of week
        if ts.get("day_of_week"):
            dow = ts["day_of_week"]
            peak_day = max(dow.items(), key=lambda x: x[1])
            context["peak_day"] = f"{peak_day[0]} with {peak_day[1]} violations"
            context["day_of_week_breakdown"] = dow

        # Top junctions
        if ts.get("top_junctions"):
            context["top_junctions"] = ts["top_junctions"][:10]

        # Vehicle types
        if ts.get("vehicle_types"):
            context["vehicle_types"] = ts["vehicle_types"][:6]

        # Violation types
        if ts.get("violation_types"):
            context["violation_types"] = ts["violation_types"][:6]

        # Resolution buckets
        if ts.get("resolution_buckets"):
            context["resolution_time_distribution"] = ts["resolution_buckets"]

    context_json = json.dumps(context, default=str)

    # ------------------------------------------------------------------
    # 3. Guard: API key required
    # ------------------------------------------------------------------
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return JSONResponse(
            content={
                "answer": "AI Q&A requires the GROQ_API_KEY environment variable to be set.",
                "mock": True,
            }
        )

    # ------------------------------------------------------------------
    # 4. Call Groq (OpenAI-compatible API)
    # ------------------------------------------------------------------
    try:
        from openai import OpenAI  # noqa: PLC0415  (deferred import)

        client = OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )

        system_prompt = (
            "You are ParkIQ's AI analyst for Bangalore traffic police. "
            "You have COMPLETE access to the parking violation dataset analysis below. "
            "ALWAYS cite specific numbers, hours, junction names, and counts from the data. "
            "NEVER say the data doesn't contain something — if it's in the context, use it. "
            "Keep answers under 120 words, be direct and actionable.\n\n"
            f"FULL DATA CONTEXT:\n{context_json}"
        )

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=512,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": request.question},
            ],
        )

        answer = response.choices[0].message.content
        return JSONResponse(content={"answer": answer})

    except Exception as e:  # noqa: BLE001
        return JSONResponse(
            content={
                "answer": f"AI service error: {str(e)}",
                "error": True,
            }
        )
