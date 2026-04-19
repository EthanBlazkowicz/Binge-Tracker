# Binge Tracker

A high-performance web application for tracking binge-watching progress across multiple IMDB titles. Featuring a sleek, high-contrast cinematic dark theme optimized for 4K displays.

## Features
- **Multi-Show Targets**: Import multiple IMDB titles (e.g., a series and its spin-offs) into a single "Binge Target".
- **Per-Show End Points**: Set independent binge endpoint episodes for each show within a target (right-click).
- **Dynamic Progress**: Interactive episode grid with hover tooltips for runtime and titles.
- **Goal Calculation**: Set a "Target End Date" to calculate exactly how many minutes per day you need to watch.
- **Reorder Targets**: Move targets up/down with animated visual swap effect.
- **Compact UI**: Action bar with inline stats (mins/day, deadline) for efficient screen space usage.
- **Cinematic UI**: Sleek, dark, high-contrast interface with fluid scroll-triggered animations.
- **Mobile Responsive**: Responsive layout with breakpoints at 768px and 400px, long-press support for touch devices.
- **Background Customization**: Built-in background selector (Dark Black, Space Grey, Dynamic Blue, Shadow Gradient, Deep Purple).
- **Persistent Storage**: SQLite database integration with volume support for Docker.

## Local Setup
1. Create a virtual environment: `python -m venv .venv`
2. Activate it:
   - Windows (PowerShell): `.\.venv\Scripts\Activate.ps1`
   - Windows (CMD): `.\.venv\Scripts\activate.bat`
   - Linux/Mac: `source .venv/bin/activate`
3. Install dependencies: `pip install -r requirements.txt`
4. Run the app: `python app.py`
5. Visit `http://localhost:5000`

**Note**: The app creates a `./data` directory automatically for the SQLite database.

## Docker Deployment
The easiest way to run Binge Tracker is using Docker Compose:

```bash
docker-compose up -d --build
```

Your data will be persisted in the `./data` directory on your host machine.

## Technical Details
- **Backend**: Flask (Python 3.11)
- **Frontend**: Vanilla JS / CSS3 (Glassmorphism with CSS variables)
- **Database**: SQLite3 (stored in `./data/binge.db`)
- **Data Source**: IMDB API (imdbapi.dev)
- **Dependencies**: flask, requests, urllib3

## Usage
1. **Add a target**: Enter IMDB title IDs (e.g., `tt3322312, tt18923754`) and optional end date
2. **Mark episodes watched**: Left-click on episode boxes
3. **Set end point**: Right-click (or long-press on mobile) an episode to set the binge endpoint for that show
4. **Refresh**: Click ↻ to fetch new episodes or update metadata
5. **Reorder**: Use ▲/▼ buttons to move targets up/down
6. **Delete**: Remove a target entirely
ns to move targets up/down
6. **Delete**: Remove a target entirely
