# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Binge Tracker is a Flask web application for tracking binge-watching progress across multiple IMDB titles. It uses a standard Flask directory structure separating backend routes, HTML templates, and static assets.

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

**Standard Flask architecture**:
- `app.py` contains all backend logic and API routes
- `templates/index.html` holds the frontend HTML
- `static/css/style.css` and `static/js/script.js` hold the separated assets
- SQLite database stored in `./data/binge.db`

**Database schema:**
- `targets`: Binge tracking goals (id, name, poster_url, end_date, calc_end_episode_id, order_index)
- `episodes`: Individual episodes linked to targets (id, target_id, show_id, show_title, season, episode, title, runtime_minutes, watched, is_end_episode)

**Key migrations:**
- `calc_end_episode_id`: Added for tracking calculated end episode
- `order_index`: Added for custom target ordering (DESC sort, higher = top)
- `is_end_episode`: Per-show end point marker (one per show within a target)
- `show_title`: Episode-level show title for multi-show targets

**Key data flow:**
1. User inputs IMDB title IDs (e.g., `tt3322312, tt18923754`) via form
2. App fetches show metadata and episodes from `api.imdbapi.dev`
3. Episodes paginated with `pageSize=50` and `pageToken`
4. Multiple shows can be grouped into a single target (spin-offs, franchise)
5. User marks episodes watched (left-click) or sets end point per show (right-click)
6. Progress calculated by summing runtime_minutes of watched vs. total episodes up to end point (per-show)

**IMDB API integration:**
- `https://api.imdbapi.dev/titles/{show_id}` - Show metadata (primaryTitle, primaryImage)
- `https://api.imdbapi.dev/titles/{show_id}/episodes?pageSize=50` - Episodes (paginated with nextPageToken)
- Episode data: season, episodeNumber, title, runtimeSeconds
- Poster URLs transformed: `._V1_` replaced with `.jpg` for high quality

**Frontend structure:**
- Vanilla JS with inline event handlers
- High-contrast cinematic dark theme with sharp borders and fluid scroll reveal animations
- Compact action bar with buttons and inline stats (mins/day, deadline)
- Background customization stored in localStorage (`bingeBg` key)
- Animated move up/down with visual swap effect
- Per-show end point tracking (right-click sets end episode per show within target)
- AJAX updates via `fetch()` for toggle/set_end/delete/refresh/move endpoints
- Mobile responsive design with breakpoints at 768px and 400px
- Long-press (500ms) on episodes to set end point on touch devices

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