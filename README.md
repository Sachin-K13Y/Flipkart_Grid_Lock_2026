# 🅿 ParkIQ — AI-Driven Parking Intelligence System

> Real-time hotspot detection, congestion impact scoring, and LLM-powered enforcement recommendations for Traffic Control Room Operators.

---

## Project Overview

ParkIQ is an AI-driven parking violation intelligence system built for urban Traffic Control Room Operators. It solves the daily challenge of deciding *where* to deploy limited enforcement teams across a city: instead of relying on intuition or static zone maps, operators get a live, data-driven dashboard that pinpoints the highest-impact illegal parking hotspots, ranks them by congestion severity, and surfaces plain-English recommendations on when and how to intervene.

At its core, ParkIQ runs a fully automated pipeline: operators upload a CSV of parking violation records (or start immediately with 500 synthetic Bangalore records), the backend applies DBSCAN spatial clustering to group violations into hotspots, computes a weighted Congestion Impact Score for each cluster, runs temporal analysis to identify peak enforcement windows, and calls Claude claude-sonnet-4-6 to generate natural-language recommendations — all rendered on an interactive Leaflet map and Chart.js dashboard, updated in real time.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                     BROWSER (Frontend)                   │
│  index.html + Leaflet + Chart.js + Vanilla JS           │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP/JSON (localhost:8000)
┌──────────────────────▼──────────────────────────────────┐
│                    FastAPI Backend                        │
│  POST /api/upload  GET /api/hotspots  GET /api/dashboard │
│  GET /api/heatmap-data  GET /api/time-stats              │
│  GET /api/recommendations  POST /api/ask                 │
├─────────────────────────────────────────────────────────┤
│              Core Processing Pipeline                    │
│  loader.py → clustering.py → impact_scorer.py           │
│            → time_analysis.py → recommender.py          │
└──────────────────────┬──────────────────────────────────┘
                       │ Anthropic Python SDK
                 ┌─────▼─────────┐
                 │  Claude API    │
                 │ claude-sonnet- │
                 │     4-6        │
                 └───────────────┘
```

---

## Setup Instructions

```bash
# 1. Clone / navigate to the project
cd parkiq/backend

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Set your Anthropic API key (optional — mock recommendations used if not set)
export ANTHROPIC_API_KEY=your_key_here
# On Windows: set ANTHROPIC_API_KEY=your_key_here

# 4. Start the backend server
python main.py
# Server starts at http://localhost:8000

# 5. Open the frontend
# Option A: Open parkiq/frontend/index.html directly in your browser
# Option B: Serve with a simple HTTP server (recommended for Chrome)
cd parkiq/frontend && python -m http.server 3000
# Then open http://localhost:3000 in your browser
```

---

## Usage Guide

**Step 1 — Instant demo:** The dashboard loads automatically with 500 synthetic Bangalore violation records. No CSV needed to explore the full feature set.

**Step 2 — Upload your data:** Click "Upload CSV" in the header (or drag-and-drop a file onto the button) to load your own police violation dataset. The backend processes the file through the full pipeline and refreshes all panels automatically.

**Step 3 — Explore the map:** View the heatmap overlay and colored cluster markers on the Leaflet map. Click any marker to see a popup with the cluster ID, violation count, impact score, priority tier, dominant violation type, and recommended enforcement time. Use the layer toggle checkboxes to show/hide the heatmap and cluster layers independently.

**Step 4 — Read AI recommendations:** The right panel displays AI-generated enforcement recommendation cards for the top 5 hotspot clusters. Each card shows the cluster ID, priority tier badge, a plain-English problem description, the recommended enforcement action, and the best time window to deploy teams.

**Step 5 — Ask the AI:** Type any natural language question about the data into the "Ask AI" text box (e.g., "Which junction has the worst peak-hour congestion?") and press Enter or click Ask. Claude answers in under 150 words, contextualized with live cluster data.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/upload | Upload CSV, run full pipeline |
| GET | /api/dashboard | Summary stats |
| GET | /api/hotspots | GeoJSON cluster data |
| GET | /api/heatmap-data | Heatmap points |
| GET | /api/time-stats | Temporal analysis |
| GET | /api/top-junctions | Top 10 junctions |
| GET | /api/recommendations | AI recommendations |
| POST | /api/ask | AI Q&A |
| GET | /api/export/report | Full JSON report |

All endpoints return `application/json`. Endpoints that require uploaded data return HTTP 400 with a descriptive message if called before any data is loaded.

---

## Key AI/ML Techniques

- **DBSCAN Spatial Clustering**: Density-based clustering (`eps=0.0008°`, `min_samples=5`) using Haversine distance with the ball_tree algorithm. Naturally handles irregular cluster shapes and marks isolated violations as noise (shown on heatmap only, not as cluster markers).

- **Weighted Impact Scoring**: Multi-factor Congestion Impact Score (0–100) combining violation frequency (35%), peak-hour concentration (25%), resolution speed (20%), vehicle diversity (10%), and junction coverage (10%) via min-max normalized weighted sum.

- **LLM-Powered Recommendations**: Claude claude-sonnet-4-6 generates natural language enforcement recommendations for the top 5 clusters and answers operator free-form questions contextualized with live cluster statistics. Gracefully degrades to mock recommendations when the API key is not set.

- **Temporal Pattern Analysis**: Hourly, daily, and weekly violation breakdowns identify optimal enforcement windows. Peak hours (07:00–09:00, 17:00–20:00) are highlighted throughout the dashboard for quick visual prioritization.

---

## Dataset Column Reference

| Column | Type | Description |
|--------|------|-------------|
| id | int | Unique violation record ID |
| latitude | float | GPS latitude of violation |
| longitude | float | GPS longitude of violation |
| location | str | Location description |
| vehicle_number | str | Vehicle plate number |
| vehicle_type | str | Vehicle category (Car, Truck, etc.) |
| violation_type | str | Type of parking violation |
| offence_code | str | Offence code |
| created_datetime | datetime | When violation was reported |
| closed_datetime | datetime | When violation was resolved |
| junction_name | str | Nearest junction |
| police_station | str | Responsible police station |
| validation_status | str | VALID / INVALID |

---

## Deliverable Checklist

- [x] CSV upload works and triggers full pipeline
- [x] Map shows heatmap + colored cluster markers
- [x] Cluster popup shows impact score and priority tier
- [x] All 4 charts render with real data
- [x] AI recommendation cards appear for top 5 hotspots
- [x] Free-form AI Q&A works
- [x] Synthetic data loads on first run (no CSV needed to demo)
- [x] Priority tier coloring is consistent across map + cards + badges
- [x] README has setup instructions
