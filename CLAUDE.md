# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Binge Tracker is a single-page Flask web application for tracking binge-watching progress across multiple IMDB titles. The entire application is contained in `app.py` with embedded HTML/CSS/JS templates.

## Running the Application

**Local development:**
```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1  # Windows
pip install -r requirements.txt
python app.py
```
Visit `http://localhost:5000`

**Docker:**
```bash
docker-compose up -d --build
```
Data persists in `./data` directory on host.

## Architecture

**Single-file Flask application** (`app.py`):
- Backend logic and HTML template are combined in one file
- `HTML_TEMPLATE` constant contains the entire frontend (HTML/CSS/JS)
- SQLite database stored in `./data/binge.db`

**Database schema:**
- `targets`: Binge tracking goals (name, poster_url, end_date, order_index)
- `episodes`: Individual episodes linked to targets (show_id, season, episode, runtime_minutes, watched, is_end_episode)

**Key data flow:**
1. User inputs IMDB title IDs (e.g., `tt3322312`) via form
2. App fetches show metadata and episodes from `api.imdbapi.dev`
3. Episodes paginated with `pageSize=50` and `pageToken`
4. User marks episodes watched (left-click) or sets end point (right-click)
5. Progress calculated by summing runtime_minutes of watched vs. total episodes up to end point

**IMDB API integration:**
- `https://api.imdbapi.dev/titles/{show_id}` - Show metadata
- `https://api.imdbapi.dev/titles/{show_id}/episodes?pageSize=50` - Episodes (paginated)
- Poster URLs transformed: `._V1_` replaced with `.jpg` for high quality

**Frontend structure:**
- Vanilla JS with inline event handlers
- Glassmorphism CSS using CSS variables in `:root`
- Compact action bar with buttons and inline stats (mins/day, deadline)
- Background customization stored in localStorage (`bingeBg` key)
- AJAX updates via `fetch()` for toggle/set_end/delete/refresh/move endpoints

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET/POST | Main page / Create target |
| `/toggle/<ep_id>` | POST | Toggle episode watched status |
| `/set_end/<ep_id>` | POST | Set binge endpoint for show |
| `/refresh/<target_id>` | POST | Fetch new episodes from IMDB |
| `/delete/<target_id>` | POST | Delete target and episodes |
| `/move/<target_id>/<direction>` | POST | Reorder target (up/down) |

## Dependencies

- `flask`: Web framework
- `requests`: HTTP client for IMDB API
- `urllib3`: HTTP library (transitive)
