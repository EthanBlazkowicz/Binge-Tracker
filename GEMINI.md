# GEMINI.md

## Project Overview
Binge Tracker is a modern, high-performance web application designed for tracking binge-watching progress across multiple IMDB titles. It features a sleek, high-contrast cinematic dark theme optimized for high-resolution displays and supports grouping multiple related shows (e.g., a main series and its spin-offs) into a single "Binge Target".

### Core Technologies
- **Backend**: Flask (Python 3.11)
- **Frontend**: Vanilla JavaScript & CSS3 (Cinematic Dark Theme)
- **Database**: SQLite3
- **External API**: IMDB API (via `api.imdbapi.dev`)
- **Containerization**: Docker & Docker Compose

### Architecture
The project follows a standard **Separation of Concerns** Flask architecture.
- **Backend Logic**: Contained in `app.py`, focusing purely on routes and IMDB API integration.
- **Frontend Structure**: HTML in `templates/index.html`, with separated `static/css/style.css` and `static/js/script.js`.
- **Database Schema**: Managed via SQLite with automatic migrations handled in `init_db()`.
- **Data Persistence**: SQLite database is stored in the `./data/` directory, which is persisted via Docker volumes.

## Building and Running

### Local Development
1. **Initialize Environment**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Linux/Mac
   # OR
   .\.venv\Scripts\Activate.ps1 # Windows
   ```
2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
3. **Run Application**:
   ```bash
   python app.py
   ```
   Access the app at `http://localhost:5000`.

### Docker Deployment
Run the application using Docker Compose:
```bash
docker-compose up -d --build
```

## Development Conventions

### Coding Style
- **Separation of Concerns**: Python backend code in `app.py`, HTML structure in `templates/index.html`, CSS styling in `static/css/style.css`, and JS logic in `static/js/script.js`.
- **Frontend Integration**: Keep UI elements decoupled from backend routes using standard Flask templates and static serving.
- **Database Migrations**: Add new columns using `TRY...EXCEPT` blocks in the `init_db()` function to ensure backward compatibility for existing SQLite databases.

### Key Features to Maintain
- **Multi-Show Targets**: Ensure that targets can still accept comma-separated IMDB IDs.
- **Cinematic UI**: Maintain the sleek, dark, high-contrast design with sharp borders and fluid animations.
- **Mobile Responsiveness**: Always test changes against the 768px and 400px breakpoints.
- **Per-Show End Points**: Right-click/Long-press functionality for setting end episodes must be preserved.

### Testing
- **Manual Verification**: Since the app relies heavily on external API calls and CSS effects, manual testing in the browser is essential.
- **Logic Testing**: Use `test_scripts/binge_tracker.py` as a reference for validating progress calculation logic independent of the web server.

## Key Files
- `app.py`: Backend routing and logic.
- `templates/index.html`: Frontend HTML markup.
- `static/css/style.css`: Application styling.
- `static/js/script.js`: Frontend interactivity and AJAX calls.
- `requirements.txt`: Python package dependencies (`flask`, `requests`, `urllib3`).
- `docker-compose.yml`: Docker service definition.
- `data/binge.db`: The SQLite database (created automatically).
- `test_scripts/binge_tracker.py`: Standalone progress calculation logic.