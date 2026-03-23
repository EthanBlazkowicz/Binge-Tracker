import sqlite3
import requests
import math
import os
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string, redirect, url_for

app = Flask(__name__)
DB_DIR = 'data'
DB_FILE = os.path.join(DB_DIR, 'binge.db')

def get_db():
    if not os.path.exists(DB_DIR):
        os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                poster_url TEXT,
                end_date TEXT,
                calc_end_episode_id INTEGER,
                order_index INTEGER DEFAULT 0
            )
        ''')
        # Migrations for existing databases
        try:
            conn.execute('ALTER TABLE targets ADD COLUMN calc_end_episode_id INTEGER')
        except sqlite3.OperationalError: pass
        try:
            conn.execute('ALTER TABLE targets ADD COLUMN order_index INTEGER DEFAULT 0')
            # Initialize order_index with current ID for existing rows
            conn.execute('UPDATE targets SET order_index = id WHERE order_index = 0')
        except sqlite3.OperationalError: pass
            
        conn.execute('''
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_id INTEGER,
                show_id TEXT,
                show_title TEXT,
                season INTEGER,
                episode INTEGER,
                title TEXT,
                runtime_minutes INTEGER,
                watched INTEGER DEFAULT 0
            )
        ''')

def get_high_quality_poster(url):
    if not url: return ""
    if '._V1_' in url:
        return url.split('._V1_')[0] + '.jpg'
    return url

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        title_ids_raw = request.form.get('title_ids', '')
        end_date = request.form.get('end_date', '')
        
        show_ids = [s.strip() for s in title_ids_raw.split(',') if s.strip()]
        
        if show_ids:
            with get_db() as conn:
                first_show_id = show_ids[0]
                target_name = f"Target {first_show_id}"
                poster_url = ""
                try:
                    res = requests.get(f"https://api.imdbapi.dev/titles/{first_show_id}")
                    if res.status_code == 200:
                        data = res.json()
                        target_name = data.get('primaryTitle', target_name)
                        if 'primaryImage' in data and data['primaryImage']:
                            poster_url = get_high_quality_poster(data['primaryImage'].get('url'))
                except Exception as e:
                    print(f"Error fetching target info: {e}")
                
                cur = conn.cursor()
                # Use current max order_index + 1 to put new targets at the top (since we sort DESC)
                cur.execute('''
                    INSERT INTO targets (name, poster_url, end_date, order_index) 
                    VALUES (?, ?, ?, (SELECT IFNULL(MAX(order_index), 0) + 1 FROM targets))
                ''', (target_name, poster_url, end_date))
                target_id = cur.lastrowid
                
                for show_id in show_ids:
                    show_title = f"Show {show_id}"
                    try:
                        res = requests.get(f"https://api.imdbapi.dev/titles/{show_id}")
                        if res.status_code == 200:
                            data = res.json()
                            show_title = data.get('primaryTitle', show_title)
                    except: pass
                        
                    page_token = None
                    while True:
                        url = f"https://api.imdbapi.dev/titles/{show_id}/episodes?pageSize=50"
                        if page_token: url += f"&pageToken={page_token}"
                            
                        try:
                            res = requests.get(url)
                            if res.status_code != 200: break
                            data = res.json()
                            eps = data.get('episodes', data) if isinstance(data, dict) else data
                            if not eps: break
                            
                            for ep in eps:
                                try:
                                    s = int(ep.get('season', 0))
                                    e = int(ep.get('episodeNumber', 0))
                                except: continue
                                    
                                title = ep.get('title', 'Unknown')
                                runtime_sec = ep.get('runtimeSeconds') or 0
                                runtime_min = runtime_sec // 60
                                
                                cur.execute('''
                                    INSERT INTO episodes (target_id, show_id, show_title, season, episode, title, runtime_minutes)
                                    VALUES (?, ?, ?, ?, ?, ?, ?)
                                ''', (target_id, show_id, show_title, s, e, title, runtime_min))
                                
                            page_token = data.get('nextPageToken')
                            if not page_token: break
                        except Exception as e:
                            print(f"Error fetching episodes: {e}")
                            break
                conn.commit()
        return redirect(url_for('index'))
        
    with get_db() as conn:
        targets_db = conn.execute('SELECT * FROM targets ORDER BY order_index DESC').fetchall()
        targets = []
        for t in targets_db:
            episodes_db = conn.execute('SELECT * FROM episodes WHERE target_id = ? ORDER BY id', (t['id'],)).fetchall()
            shows = {}
            for ep in episodes_db:
                show_k = ep['show_title']
                if show_k not in shows: shows[show_k] = {}
                season_k = ep['season']
                if season_k not in shows[show_k]: shows[show_k][season_k] = []
                shows[show_k][season_k].append(ep)
                
            stats = calculate_target_stats(t['id'], conn)
            targets.append({
                'id': t['id'],
                'name': t['name'],
                'poster_url': t['poster_url'],
                'end_date': t['end_date'],
                'shows': shows,
                'stats': stats
            })

    return render_template_string(HTML_TEMPLATE, targets=targets)

@app.route('/toggle/<int:ep_id>', methods=['POST'])
def toggle_watched(ep_id):
    with get_db() as conn:
        cur = conn.cursor()
        ep = cur.execute('SELECT watched, target_id FROM episodes WHERE id = ?', (ep_id,)).fetchone()
        if ep:
            new_watched = 0 if ep['watched'] else 1
            cur.execute('UPDATE episodes SET watched = ? WHERE id = ?', (new_watched, ep_id))
            conn.commit()
            stats = calculate_target_stats(ep['target_id'], conn)
            return jsonify({
                'success': True, 
                'watched': new_watched, 
                'target_id': ep['target_id'],
                'stats': stats
            })
    return jsonify({'success': False})

@app.route('/set_end/<int:ep_id>', methods=['POST'])
def set_end_ep(ep_id):
    with get_db() as conn:
        cur = conn.cursor()
        ep = cur.execute('SELECT target_id FROM episodes WHERE id = ?', (ep_id,)).fetchone()
        if ep:
            target_id = ep['target_id']
            target = cur.execute('SELECT calc_end_episode_id FROM targets WHERE id = ?', (target_id,)).fetchone()
            new_end_id = None if target['calc_end_episode_id'] == ep_id else ep_id
            cur.execute('UPDATE targets SET calc_end_episode_id = ? WHERE id = ?', (new_end_id, target_id))
            conn.commit()
            return jsonify({'success': True, 'target_id': target_id})
    return jsonify({'success': False})

@app.route('/delete/<int:target_id>', methods=['POST'])
def delete_target(target_id):
    with get_db() as conn:
        conn.execute('DELETE FROM targets WHERE id = ?', (target_id,))
        conn.execute('DELETE FROM episodes WHERE target_id = ?', (target_id,))
        conn.commit()
    return jsonify({'success': True})

@app.route('/move/<int:target_id>/<string:direction>', methods=['POST'])
def move_target(target_id, direction):
    with get_db() as conn:
        cur = conn.cursor()
        current = cur.execute('SELECT order_index FROM targets WHERE id = ?', (target_id,)).fetchone()
        if not current: return jsonify({'success': False})
        
        curr_val = current['order_index']
        
        if direction == 'up':
            # Find the one immediately "above" in the DESC sort (higher order_index)
            neighbor = cur.execute('SELECT id, order_index FROM targets WHERE order_index > ? ORDER BY order_index ASC LIMIT 1', (curr_val,)).fetchone()
        else:
            # Find the one immediately "below" in the DESC sort (lower order_index)
            neighbor = cur.execute('SELECT id, order_index FROM targets WHERE order_index < ? ORDER BY order_index DESC LIMIT 1', (curr_val,)).fetchone()
            
        if neighbor:
            cur.execute('UPDATE targets SET order_index = ? WHERE id = ?', (neighbor['order_index'], target_id))
            cur.execute('UPDATE targets SET order_index = ? WHERE id = ?', (curr_val, neighbor['id']))
            conn.commit()
            return jsonify({'success': True})
            
    return jsonify({'success': False})

def calculate_target_stats(target_id, conn):
    target = conn.execute('SELECT end_date, calc_end_episode_id FROM targets WHERE id = ?', (target_id,)).fetchone()
    end_ep_id = target['calc_end_episode_id'] if target else None
    if end_ep_id:
        episodes = conn.execute('SELECT runtime_minutes, watched FROM episodes WHERE target_id = ? AND id <= ?', (target_id, end_ep_id)).fetchall()
    else:
        episodes = conn.execute('SELECT runtime_minutes, watched FROM episodes WHERE target_id = ?', (target_id,)).fetchall()
    total_min = sum(ep['runtime_minutes'] for ep in episodes)
    watched_min = sum(ep['runtime_minutes'] for ep in episodes if ep['watched'])
    remaining_min = total_min - watched_min
    progress = (watched_min / total_min * 100) if total_min > 0 else 0
    stats_text = f"Total: {total_min} min | Watched: {watched_min} min | Remaining: {remaining_min} min"
    min_per_day = None
    if target and target['end_date'] and remaining_min > 0:
        try:
            end_date_obj = datetime.strptime(target['end_date'], "%Y-%m-%d").date()
            days_left = (end_date_obj - datetime.now().date()).days
            if days_left <= 0: days_left = 1
            min_per_day = math.ceil(remaining_min / days_left)
        except ValueError: pass
    return {
        'progress_percent': round(progress, 2),
        'text': stats_text,
        'daily_mins': min_per_day,
        'end_ep_id': end_ep_id
    }

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Binge Tracker</title>
    <style>
        /* Neutral Glass Theme */
        :root {
            --glass-bg: rgba(255, 255, 255, 0.15);
            --glass-border: rgba(255, 255, 255, 0.2);
            --glass-blur: blur(25px);
            --primary-blue: #0A84FF;
            --primary-green: #30D158;
            --accent-red: #FF453A;
            --text-white: #FFFFFF;
            --banner-width: 80vw;
        }

        body { 
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", sans-serif; 
            margin: 0; padding: 60px 0; color: var(--text-white);
            background: #000;
            display: flex; flex-direction: column; align-items: center;
            min-height: 100vh;
            transition: background 0.5s ease;
        }

        .banner-container { width: var(--banner-width); margin-bottom: 40px; box-sizing: border-box; }

        /* Glass Panel Styling */
        .glass-panel {
            background: var(--glass-bg);
            backdrop-filter: var(--glass-blur);
            -webkit-backdrop-filter: var(--glass-blur);
            border: 1px solid var(--glass-border);
            border-radius: 24px;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        }

        /* Title Banner */
        .title-banner { padding: 40px; text-align: center; }
        .title-banner h1 { margin: 0; font-size: 48px; font-weight: 800; letter-spacing: -1.5px; }

        /* Target Cards */
        .target-card { 
            width: var(--banner-width); padding: 30px; box-sizing: border-box; 
            margin-bottom: 40px; display: flex; flex-direction: column;
        }

        .target-header { display: flex; gap: 30px; height: 400px; }
        .target-poster { height: 100%; width: 280px; border-radius: 16px; object-fit: cover; box-shadow: 0 10px 30px rgba(0,0,0,0.5); flex-shrink: 0; }
        .target-info { flex: 1; display: flex; flex-direction: column; min-width: 0; padding-top: 10px; }
        .target-title-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; padding-right: 5px; }
        .target-info h2 { margin: 0; font-size: 32px; font-weight: 700; }
        
        .action-group { display: flex; gap: 10px; }
        .btn { background: rgba(255,255,255,0.1); color: white; border: 1px solid rgba(255,255,255,0.2); border-radius: 10px; padding: 10px 15px; cursor: pointer; font-weight: 600; font-size: 14px; transition: all 0.2s; display: flex; align-items: center; justify-content: center; }
        .btn:hover { background: rgba(255,255,255,0.25); transform: translateY(-1px); }
        .btn.delete-btn { background: rgba(255, 69, 58, 0.2); border-color: rgba(255, 69, 58, 0.4); }
        .btn.delete-btn:hover { background: rgba(255, 69, 58, 0.5); }

        .show-list-container { flex: 1; overflow-y: auto; padding-right: 20px; }

        /* Stats Blocks */
        .stats-right-panel { display: flex; gap: 15px; flex-shrink: 0; }
        .glass-box { 
            background: rgba(255, 255, 255, 0.1); border: 1px solid rgba(255,255,255,0.15);
            border-radius: 20px; padding: 25px; min-width: 140px;
            display: flex; flex-direction: column; justify-content: center; align-items: center;
        }
        .daily-num { font-size: 42px; font-weight: 800; line-height: 1; margin-bottom: 8px; }
        .daily-label { font-size: 14px; color: rgba(255,255,255,0.6); text-transform: uppercase; font-weight: 700; letter-spacing: 1px; }

        .show-title { font-size: 18px; font-weight: 700; margin-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 6px; margin-top: 20px; }
        .season-row { display: flex; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 10px; }
        .season-label { font-weight: 600; width: 100px; color: rgba(255,255,255,0.5); font-size: 15px; }

        /* Episode Boxes */
        .ep-box { 
            width: 38px; height: 38px; background: rgba(255,255,255,0.08); 
            display: flex; align-items: center; justify-content: center; border-radius: 10px; 
            cursor: pointer; font-size: 15px; font-weight: 600; 
            border: 1px solid rgba(255,255,255,0.1); transition: all 0.2s; user-select: none; position: relative;
        }
        .ep-box:hover { background: rgba(255,255,255,0.2); transform: scale(1.1); z-index: 999; }
        .ep-box.watched { background: var(--primary-green); border-color: transparent; color: #000; }
        .ep-box.dimmed { opacity: 0.15; }
        .ep-box.end-ep { border: 2px solid var(--accent-red); background: rgba(255, 69, 58, 0.1); }

        /* Progress Area */
        .progress-wrapper { margin-top: 30px; }
        .progress-container { background: rgba(255,255,255,0.05); height: 32px; border-radius: 16px; overflow: hidden; border: 1px solid rgba(255,255,255,0.1); position: relative; }
        .progress-bar { background: #FFFFFF; height: 100%; transition: width 0.8s cubic-bezier(0.23, 1, 0.32, 1); }
        .progress-text-overlay { position: absolute; width: 100%; text-align: center; top: 0; left: 0; line-height: 32px; font-size: 14px; font-weight: 700; mix-blend-mode: difference; }
        .stats-text { margin-top: 12px; font-size: 15px; color: rgba(255,255,255,0.5); text-align: center; font-weight: 500; }

        /* Form Area */
        .form-banner { width: var(--banner-width); padding: 40px; box-sizing: border-box; margin-top: 40px; }
        .form-banner h2 { margin-top: 0; margin-bottom: 25px; font-size: 28px; font-weight: 700; }
        .form-banner label { color: rgba(255,255,255,0.5); font-weight: 600; font-size: 14px; margin-bottom: 10px; display: block; }
        .form-banner input { 
            padding: 16px 20px; margin-bottom: 20px; width: 100%; 
            box-sizing: border-box; border: 1px solid rgba(255,255,255,0.1); 
            border-radius: 14px; background: rgba(255,255,255,0.05); 
            color: #fff; font-size: 17px; outline: none;
        }
        .form-banner button { 
            padding: 18px; background: #fff; color: #000; border: none; 
            border-radius: 14px; cursor: pointer; font-size: 18px; font-weight: 700; 
            width: 100%; transition: all 0.2s;
        }
        .form-banner button:hover { transform: translateY(-2px); box-shadow: 0 10px 20px rgba(255,255,255,0.2); }

        /* Global Tooltip */
        #global-tooltip {
            position: fixed;
            background: rgba(255,255,255,0.95); color: #000; padding: 10px 15px; border-radius: 12px;
            white-space: nowrap; font-size: 13px; font-weight: 600;
            z-index: 99999; opacity: 0; pointer-events: none; transition: opacity 0.2s, transform 0.2s;
            box-shadow: 0 4px 15px rgba(0,0,0,0.3);
            transform: translateX(-50%) translateY(10px);
            left: 0; top: 0;
        }
        #global-tooltip.show { opacity: 1; transform: translateX(-50%) translateY(0); }

        /* Settings Icon */
        .settings-btn { position: fixed; top: 30px; right: 30px; background: rgba(255,255,255,0.15); backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,0.2); border-radius: 50%; width: 50px; height: 50px; display: flex; align-items: center; justify-content: center; cursor: pointer; z-index: 1000; color: #fff; }

        .bg-menu { position: fixed; top: 90px; right: 30px; background: rgba(255,255,255,0.15); backdrop-filter: blur(20px); border: 1px solid rgba(255,255,255,0.2); border-radius: 18px; padding: 15px; display: none; flex-direction: column; gap: 10px; z-index: 1000; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }
        .bg-option { padding: 10px 20px; border-radius: 10px; cursor: pointer; font-size: 14px; font-weight: 600; color: #fff; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); text-align: center; }
        .bg-option:hover { background: rgba(255,255,255,0.2); }
    </style>
    <script>
        function setBg(bgStyle) { document.body.style.background = bgStyle; localStorage.setItem('bingeBg', bgStyle); }
        window.onload = () => { 
            const savedBg = localStorage.getItem('bingeBg'); 
            if (savedBg) document.body.style.background = savedBg; 

            const tooltip = document.getElementById('global-tooltip');
            document.querySelectorAll('.ep-box').forEach(box => {
                box.addEventListener('mouseenter', (e) => {
                    const rect = box.getBoundingClientRect();
                    tooltip.textContent = box.getAttribute('data-tooltip');
                    tooltip.style.left = (rect.left + rect.width / 2) + 'px';
                    tooltip.style.top = (rect.top - 10) + 'px';
                    tooltip.classList.add('show');
                });
                box.addEventListener('mouseleave', () => {
                    tooltip.classList.remove('show');
                });
            });
        }
        function toggleMenu() { const menu = document.getElementById('bgMenu'); menu.style.display = (menu.style.display === 'flex') ? 'none' : 'flex'; }

        function toggleEp(epId, element) {
            fetch('/toggle/' + epId, { method: 'POST' })
            .then(res => res.json())
            .then(data => {
                if(data.success) {
                    if(data.watched) element.classList.add('watched');
                    else element.classList.remove('watched');
                    updateStats(data.target_id, data.stats);
                }
            });
        }
        function setEndEp(event, epId) {
            event.preventDefault();
            fetch('/set_end/' + epId, { method: 'POST' })
            .then(res => res.json())
            .then(data => { if(data.success) window.location.reload(); });
        }
        function deleteTarget(targetId) {
            if(confirm("Delete this Binge Target?")) {
                fetch('/delete/' + targetId, { method: 'POST' })
                .then(res => res.json())
                .then(data => {
                    if(data.success) {
                        const elem = document.getElementById('card-' + targetId);
                        elem.style.transform = "scale(0.95)"; elem.style.opacity = 0;
                        setTimeout(() => elem.remove(), 400);
                    }
                });
            }
        }
        function moveTarget(targetId, direction) {
            const currentCard = document.getElementById('card-' + targetId);
            if (!currentCard) return;
            
            const sibling = direction === 'up' ? currentCard.previousElementSibling : currentCard.nextElementSibling;
            
            // Proceed with animation only if the sibling is another target card
            if (sibling && sibling.classList.contains('target-card')) {
                const currentRect = currentCard.getBoundingClientRect();
                const siblingRect = sibling.getBoundingClientRect();
                const dy = siblingRect.top - currentRect.top;

                // Prepare for animation
                currentCard.style.transition = 'transform 0.4s ease-in-out, box-shadow 0.4s ease-in-out';
                currentCard.style.zIndex = '100';
                currentCard.style.position = 'relative';
                
                sibling.style.transition = 'transform 0.4s ease-in-out';
                sibling.style.position = 'relative';

                // Trigger animation
                requestAnimationFrame(() => {
                    currentCard.style.transform = `translateY(${dy}px) scale(1.02)`;
                    currentCard.style.boxShadow = '0 25px 50px rgba(0,0,0,0.6)';
                    sibling.style.transform = `translateY(${-dy}px)`;
                });

                // Wait for animation, then backend call
                setTimeout(() => {
                    fetch('/move/' + targetId + '/' + direction, { method: 'POST' })
                    .then(res => res.json())
                    .then(data => { if(data.success) window.location.reload(); });
                }, 400);
            } else {
                // Fallback if no valid sibling
                fetch('/move/' + targetId + '/' + direction, { method: 'POST' })
                .then(res => res.json())
                .then(data => { if(data.success) window.location.reload(); });
            }
        }
        function updateStats(targetId, stats) {
            const bar = document.getElementById('bar-' + targetId);
            const overlay = document.getElementById('overlay-' + targetId);
            const txt = document.getElementById('stats-' + targetId);
            const daily = document.getElementById('daily-' + targetId);
            if(bar) bar.style.width = stats.progress_percent + '%';
            if(overlay) overlay.innerText = stats.progress_percent + '%';
            if(txt) txt.innerText = stats.text;
            if(daily) {
                if (stats.daily_mins != null) daily.innerHTML = '<div class="daily-num">' + stats.daily_mins + '</div><div class="daily-label">mins/day</div>';
                else daily.innerHTML = '<div class="daily-label">No Goal Date</div>';
            }
        }
    </script>
</head>
<body>
    <div id="global-tooltip"></div>

    <div class="settings-btn" onclick="toggleMenu()">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
    </div>

    <div class="bg-menu" id="bgMenu">
        <div class="bg-option" onclick="setBg('#000')">Dark Black</div>
        <div class="bg-option" onclick="setBg('#1c1c1e')">Space Grey</div>
        <div class="bg-option" onclick="setBg('linear-gradient(135deg, #a8c0ff 0%, #3f2b96 100%)')">Dynamic Blue</div>
        <div class="bg-option" onclick="setBg('linear-gradient(135deg, #2c3e50 0%, #000 100%)')">Shadow Gradient</div>
        <div class="bg-option" onclick="setBg('linear-gradient(135deg, #667eea 0%, #764ba2 100%)')">Deep Purple</div>
    </div>

    <div class="banner-container glass-panel title-banner">
        <h1>Binge Tracker</h1>
    </div>

    {% for target in targets %}
    <div class="target-card glass-panel" id="card-{{ target.id }}">
        <div class="target-header">
            {% if target.poster_url %}
            <img src="{{ target.poster_url }}" class="target-poster" alt="Poster">
            {% endif %}
            
            <div class="target-info">
                <div class="target-title-bar">
                    <h2>{{ target.name }}</h2>
                    <div class="action-group">
                        <button class="btn" onclick="moveTarget({{ target.id }}, 'up')" title="Move Up">▲</button>
                        <button class="btn" onclick="moveTarget({{ target.id }}, 'down')" title="Move Down">▼</button>
                        <button class="btn delete-btn" onclick="deleteTarget({{ target.id }})" title="Delete Target">Delete</button>
                    </div>
                </div>
                <p style="margin: 0 0 20px 0; color: rgba(255,255,255,0.4); font-size: 14px;">Right-click an episode to set binge end point.</p>
                
                <div class="show-list-container">
                    {% set is_after_end = namespace(value=false) %}
                    {% for show_title, seasons in target.shows.items() %}
                    <div class="show-section">
                        <div class="show-title">{{ show_title }}</div>
                        {% for season_num, eps in seasons.items() %}
                        <div class="season-row">
                            <div class="season-label">Season {{ season_num }}</div>
                            {% for ep in eps %}
                                {% if target.stats.end_ep_id and ep.id > target.stats.end_ep_id %}
                                    {% set is_after_end.value = true %}
                                {% else %}
                                    {% set is_after_end.value = false %}
                                {% endif %}
                                <div class="ep-box {% if ep.watched %}watched{% endif %} {% if target.stats.end_ep_id == ep.id %}end-ep{% endif %} {% if is_after_end.value %}dimmed{% endif %}" 
                                     onclick="toggleEp({{ ep.id }}, this)"
                                     oncontextmenu="setEndEp(event, {{ ep.id }})"
                                     data-tooltip="Ep {{ ep.episode }}: {{ ep.title }} ({{ ep.runtime_minutes }}m)">
                                    {{ ep.episode }}
                                </div>
                            {% endfor %}
                        </div>
                        {% endfor %}
                    </div>
                    {% endfor %}
                </div>
            </div>
            
            <div class="stats-right-panel">
                <div class="glass-box" id="daily-{{ target.id }}">
                    {% if target.stats.daily_mins != null %}
                        <div class="daily-num">{{ target.stats.daily_mins }}</div>
                        <div class="daily-label">mins/day</div>
                    {% else %}
                        <div class="daily-label">No Goal Date</div>
                    {% endif %}
                </div>
                
                {% if target.end_date %}
                <div class="glass-box" style="background: rgba(255,255,255,0.05);">
                    <div class="daily-num" style="font-size: 32px;">{{ target.end_date[5:] }}</div>
                    <div class="daily-label">{{ target.end_date[:4] }}</div>
                    <div class="daily-label" style="margin-top: 8px; color: var(--primary-blue);">Deadline</div>
                </div>
                {% endif %}
            </div>
        </div>
        
        <div class="progress-wrapper">
            <div class="progress-container">
                <div class="progress-bar" id="bar-{{ target.id }}" style="width: {{ target.stats.progress_percent }}%;"></div>
                <div class="progress-text-overlay" id="overlay-{{ target.id }}">{{ target.stats.progress_percent }}%</div>
            </div>
            <div class="stats-text" id="stats-{{ target.id }}">{{ target.stats.text }}</div>
        </div>
    </div>
    {% endfor %}

    <div class="form-banner glass-panel">
        <h2>Add New Binge Goal</h2>
        <form method="POST">
            <label>IMDB Title IDs (e.g. tt3322312, tt18923754)</label>
            <input type="text" name="title_ids" placeholder="tt1234567, tt7654321" required>
            <label>Target End Date</label>
            <input type="date" name="end_date">
            <button type="submit">Create Binge Target</button>
        </form>
    </div>

</body>
</html>
"""

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000, host='0.0.0.0')
