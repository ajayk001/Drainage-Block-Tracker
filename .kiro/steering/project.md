# DrainWatch — Project Context

## What this project is
DrainWatch is an Urban Drainage Blockage Reporting and Mapping web application built for civic use. It lets citizens report drain blockages on an interactive map, and gives municipal teams a dashboard to manage and prioritize maintenance cases.

## Tech stack
- **Backend:** Python Flask (`app.py`) + SQLite (`drainage.db`)
- **Frontend:** HTML5 + Tailwind CSS (CDN) + Leaflet.js (CDN), vanilla JS
- **Templates:** Jinja2 in `templates/` (Flask renders them server-side)
- **Uploads:** `static/uploads/` — user-submitted photos saved here

## File structure
```
app.py                        Flask backend (all routes + DB logic)
requirements.txt              Only dependency: flask>=2.3.0
drainage.db                   SQLite DB (auto-created, excluded from git)
static/uploads/               Photo uploads (excluded from git)
templates/
  index.html                  Citizen map + report form (Leaflet.js)
  dashboard.html              Municipal admin dashboard (table + status controls)
.kiro/steering/project.md     This file
```

## Running the project
```bash
pip install -r requirements.txt
python3 app.py
# App runs on http://localhost:5006
# Dashboard at http://localhost:5006/dashboard
```
Delete `drainage.db` before restarting if the schema changed.

## Database schema

### `cases` table
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | Auto-increment |
| lat, lng | REAL | Report location |
| severity | INTEGER | 1 (Low) – 5 (Critical) |
| notes | TEXT | Citizen description |
| status | TEXT | Open → Assigned → In Progress → Resolved |
| priority_score | REAL | Computed (see formula below) |
| photo_filename | TEXT | Filename in static/uploads/ |
| report_count | INTEGER | Increments on dedup merge |
| area_impact | TEXT | Residential / Commercial Hub / School Zone / Hospital Zone / Main Road |
| asset_id | INTEGER FK | Links to drain_assets if snapped within 20m |
| zone_id | TEXT | Zone-1 through Zone-5 (from snapped asset) |
| assigned_team | TEXT | Auto-assigned by zone (see team routing) |
| created_at, updated_at | TIMESTAMP | |

### `drain_assets` table
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| name | TEXT | e.g. "Zone-1 Asset A" |
| lat, lng | REAL | Physical location |
| zone_id | TEXT | Zone-1 through Zone-5 |
| asset_type | TEXT | Manhole / Drain Grate / Culvert |

15 synthetic assets seeded across Bengaluru (lat ~12.97, lng ~77.59).

## Priority score formula
```
priority_score = (severity * 0.4) + (report_count * 0.3) + (area_impact_multiplier * 0.3)
```
Area impact multipliers: Residential=1.0, Commercial Hub=2.0, Main Road=2.5, School Zone=3.0, Hospital Zone=4.0

## Deduplication logic
New reports within **25 metres** of an existing active case (non-Resolved) are merged into the nearest one. The merge:
- Increments `report_count`
- Recomputes `priority_score`
- Appends notes with ` | ` separator
- Keeps the higher `area_impact` rank
- Preserves existing photo unless new report has one

## Asset snapping
On submission, the backend checks for the nearest `drain_assets` record within **20 metres** using Haversine. If found, `asset_id`, `zone_id`, and `assigned_team` are set on the case.

## Team routing (zone → team)
| Zone | Team |
|---|---|
| Zone-1 | Zone-1 Rapid Action Team |
| Zone-2 | Zone-2 Maintenance Crew |
| Zone-3 | Zone-3 Rapid Action |
| Zone-4 | Zone-4 Civil Works |
| Zone-5 | Zone-5 Emergency Response |
| None | General Maintenance Team |

Team is auto-assigned at case creation, and re-evaluated on transition to Assigned or In Progress (upgrades from General Maintenance Team if zone is now known).

## API routes
| Method | Route | Description |
|---|---|---|
| GET | `/` | Serve index.html |
| GET | `/dashboard` | Serve dashboard.html |
| GET | `/api/cases` | All cases, ordered by priority_score DESC |
| POST | `/api/report` | Submit report (multipart/form-data: lat, lng, severity, notes, area_impact, photo) |
| PUT | `/api/cases/<id>/status` | Update status (JSON: `{"status": "Assigned"}`) |
| GET | `/api/assets` | All drain assets |
| GET | `/uploads/<filename>` | Serve uploaded photos |

## Frontend map (index.html)
- Leaflet map centered on Bengaluru [12.9716, 77.5946], zoom 13
- Case markers: colored circles scaled by priority_score
  - Open → red `#ef4444`
  - Assigned → orange `#f97316`
  - In Progress → purple `#a855f7`
  - Resolved → green `#22c55e`
- Drain assets: small blue rotated squares (diamond shape)
- Map click → sets report lat/lng
- "Use My Location" → browser geolocation
- Toast notifications for new cases, merges, and snapping

## Security notes
- All user-supplied values rendered via `esc()` helper before inserting into innerHTML
- This includes `photo_filename` in both popup and dashboard table
- Photo uploads validated by extension whitelist

## Disclaimer (required on both pages)
> ℹ️ DrainWatch tracks drainage blockages and maintenance workflows. It does not predict or model localized flood risk from individual reports alone.

Shown as amber banner in dashboard header, sidebar in index.html, and footer on both pages.

## GitHub
Repository: https://github.com/ajayk001/Drainage-Block-Tracker
Owner: ajayk001 (ajaypranav3026@gmail.com)
Branch: main
