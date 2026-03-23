# Binge Tracker

A high-performance, single-page web application for tracking binge-watching progress across multiple IMDB titles. Featuring a modern iOS-inspired "Glassmorphism" interface optimized for 4K displays.

## Features
- **Group Tracking**: Import multiple IMDB titles (e.g., a series and its spin-offs) into a single "Binge Target".
- **Dynamic Progress**: Interactive episode grid with hover tooltips for runtime and titles.
- **Goal Calculation**: Set a "Target End Date" and an "Endpoint Episode" to calculate exactly how many minutes per day you need to watch.
- **Glassmorphism UI**: Neutral, translucent interface optimized for high-resolution (4K) monitors.
- **Customization**: Built-in background selector to match your aesthetic.
- **Persistent Storage**: SQLite database integration with volume support for Docker.

## Local Setup
1. Create a virtual environment: `python -m venv .venv`
2. Activate it: `.\.venv\Scripts\Activate.ps1` (Windows)
3. Install dependencies: `pip install -r requirements.txt`
4. Run the app: `python app.py`
5. Visit `http://localhost:5000`

## Docker Deployment
The easiest way to run Binge Tracker is using Docker Compose:

```bash
docker-compose up -d --build
```

Your data will be persisted in the `./data` directory on your host machine.

## Technical Details
- **Backend**: Flask (Python 3.11)
- **Frontend**: Vanilla JS / CSS3 (Glassmorphism)
- **Database**: SQLite3
- **Data Source**: IMDB API (imdbapi.dev)
