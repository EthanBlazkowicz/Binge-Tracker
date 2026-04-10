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
                watched INTEGER DEFAULT 0,
                is_end_episode INTEGER DEFAULT 0
            )
        ''')
        try:
            conn.execute('ALTER TABLE episodes ADD COLUMN is_end_episode INTEGER DEFAULT 0')
        except sqlite3.OperationalError: pass

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
        ep = cur.execute('SELECT target_id, show_id, show_title, is_end_episode FROM episodes WHERE id = ?', (ep_id,)).fetchone()
        if ep:
            target_id = ep['target_id']
            show_id = ep['show_id']
            show_title = ep['show_title']
            currently_is_end = ep['is_end_episode']

            cur.execute('UPDATE episodes SET is_end_episode = 0 WHERE target_id = ? AND show_id = ?', (target_id, show_id))
            if not currently_is_end:
                cur.execute('UPDATE episodes SET is_end_episode = 1 WHERE id = ?', (ep_id,))

            conn.commit()
            stats = calculate_target_stats(target_id, conn)
            return jsonify({
                'success': True,
                'target_id': target_id,
                'ep_id': ep_id,
                'show_title': show_title,
                'stats': stats
            })
    return jsonify({'success': False})

@app.route('/refresh/<int:target_id>', methods=['POST'])
def refresh_target(target_id):
    with get_db() as conn:
        cur = conn.cursor()
        
        # Get unique show_ids for this target based on existing episodes
        show_ids_rows = cur.execute('SELECT DISTINCT show_id FROM episodes WHERE target_id = ? ORDER BY id', (target_id,)).fetchall()
        if not show_ids_rows:
            return jsonify({'success': False})
            
        show_ids = [row['show_id'] for row in show_ids_rows]
        
        # Update the target properties using the first show id
        first_show_id = show_ids[0]
        try:
            res = requests.get(f"https://api.imdbapi.dev/titles/{first_show_id}")
            if res.status_code == 200:
                data = res.json()
                target_name = data.get('primaryTitle')
                if 'primaryImage' in data and data['primaryImage']:
                    poster_url = get_high_quality_poster(data['primaryImage'].get('url'))
                    if target_name and poster_url:
                        cur.execute('UPDATE targets SET name = ?, poster_url = ? WHERE id = ?', (target_name, poster_url, target_id))
        except Exception as e:
            print(f"Error fetching target info during refresh: {e}")
            
        # Fetch new episodes for all shows
        for show_id in show_ids:
            try:
                res = requests.get(f"https://api.imdbapi.dev/titles/{show_id}")
                show_title = f"Show {show_id}"
                if res.status_code == 200:
                    show_title = res.json().get('primaryTitle', show_title)
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
                            
                        existing_ep = cur.execute('SELECT id FROM episodes WHERE target_id = ? AND show_id = ? AND season = ? AND episode = ?', (target_id, show_id, s, e)).fetchone()
                        
                        title = ep.get('title', 'Unknown')
                        runtime_sec = ep.get('runtimeSeconds') or 0
                        runtime_min = runtime_sec // 60
                        
                        if existing_ep:
                            cur.execute('UPDATE episodes SET title = ?, runtime_minutes = ? WHERE id = ?', (title, runtime_min, existing_ep['id']))
                        else:
                            cur.execute('''
                                INSERT INTO episodes (target_id, show_id, show_title, season, episode, title, runtime_minutes)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            ''', (target_id, show_id, show_title, s, e, title, runtime_min))
                        
                    page_token = data.get('nextPageToken')
                    if not page_token: break
                except Exception as e:
                    print(f"Error fetching episodes during refresh: {e}")
                    break
                    
        conn.commit()
        return jsonify({'success': True})

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
    target = conn.execute('SELECT end_date FROM targets WHERE id = ?', (target_id,)).fetchone()
    
    episodes = conn.execute('SELECT id, show_title, show_id, runtime_minutes, watched, is_end_episode FROM episodes WHERE target_id = ? ORDER BY id', (target_id,)).fetchall()
    
    end_eps_by_show = {}
    end_eps_by_show_id = {}
    for ep in episodes:
        if ep['is_end_episode']:
            end_eps_by_show[ep['show_title']] = ep['id']
            end_eps_by_show_id[ep['show_id']] = ep['id']
            
    valid_episodes = []
    for ep in episodes:
        show_end_id = end_eps_by_show_id.get(ep['show_id'])
        if not show_end_id or ep['id'] <= show_end_id:
            valid_episodes.append(ep)
            
    total_min = sum(ep['runtime_minutes'] for ep in valid_episodes)
    watched_min = sum(ep['runtime_minutes'] for ep in valid_episodes if ep['watched'])
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
        'end_eps_by_show': end_eps_by_show
    }

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Binge Tracker</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <style>
        /* Refined Glass Theme */
        :root {
            --glass-bg: rgba(255, 255, 255, 0.08);
            --glass-border: rgba(255, 255, 255, 0.08);
            --glass-blur: blur(40px);
            --primary-blue: rgba(10, 132, 255, 0.85);
            --primary-green: rgba(48, 209, 88, 0.85);
            --accent-red: rgba(255, 69, 58, 0.85);
            --text-white: #FFFFFF;
            --banner-width: 80vw;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", sans-serif;
            margin: 0; padding: 60px 0; color: var(--text-white);
            background: #000;
            display: flex; flex-direction: column; align-items: center;
            min-height: 100vh;
        }

        .banner-container { width: var(--banner-width); margin-bottom: 48px; box-sizing: border-box; }

        /* Glass Panel Styling */
        .glass-panel {
            background: var(--glass-bg);
            backdrop-filter: var(--glass-blur);
            -webkit-backdrop-filter: var(--glass-blur);
            border: 1px solid var(--glass-border);
            border-radius: 28px;
            box-shadow:
                0 8px 32px 0 rgba(0, 0, 0, 0.37),
                inset 0 1px 0 rgba(255, 255, 255, 0.1);
        }

        /* Title Banner */
        .title-banner { padding: 48px; text-align: center; }
        .title-banner h1 { margin: 0; font-size: 56px; font-weight: 900; letter-spacing: -2px; }

        /* Target Cards */
        .target-card {
            width: var(--banner-width); padding: 36px; box-sizing: border-box;
            margin-bottom: 48px; display: flex; flex-direction: column;
        }

        .target-header { display: flex; gap: 36px; height: 400px; }
        .target-poster {
            height: 100%; width: 280px; border-radius: 20px; object-fit: cover;
            box-shadow: 0 16px 48px rgba(0,0,0,0.4); flex-shrink: 0;
            position: relative; overflow: hidden;
        }
        .target-poster::after {
            content: ''; position: absolute; inset: 0;
            background: linear-gradient(180deg, rgba(255,255,255,0.05) 0%, transparent 60%);
        }
        .target-info { flex: 1; display: flex; flex-direction: column; min-width: 0; padding-top: 10px; }
        .target-title-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; padding-right: 5px; }
        .target-info h2 { margin: 0; font-size: 28px; font-weight: 700; }

        .action-group { display: flex; gap: 12px; align-items: center; }
        .btn {
            background: rgba(255,255,255,0.06); color: white;
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 12px; padding: 0 16px;
            cursor: pointer; font-weight: 600; font-size: 13px; line-height: 40px;
            height: 40px;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            display: flex; align-items: center; justify-content: center;
        }
        .btn:hover {
            background: rgba(255,255,255,0.15);
            transform: translateY(-2px);
            box-shadow: 0 8px 20px rgba(0,0,0,0.2);
        }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
        .btn.delete-btn {
            background: rgba(255, 69, 58, 0.1);
            border-color: rgba(255, 69, 58, 0.2);
            color: rgba(255, 200, 195, 1);
        }
        .btn.delete-btn:hover {
            background: rgba(255, 69, 58, 0.25);
            border-color: rgba(255, 69, 58, 0.4);
        }

        /* Stats Boxes - refined style */
        .stats-inline-panel { display: flex; gap: 12px; }
        .stats-box {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 12px; padding: 0 16px;
            display: flex; align-items: center; justify-content: center;
            font-size: 13px; font-weight: 600; color: white; line-height: 40px;
            height: 38px;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .stats-box:hover { background: rgba(255, 255, 255, 0.08); }
        .stats-box .num { font-weight: 700; margin-right: 5px; font-size: 13px; }
        .stats-box .label { font-size: 11px; color: rgba(255,255,255,0.5); font-weight: 500; letter-spacing: 0.3px; text-transform: uppercase; }

        .show-list-container { flex: 1; overflow-y: auto; padding-right: 24px; }
        .show-list-container::-webkit-scrollbar { width: 6px; }
        .show-list-container::-webkit-scrollbar-track { background: transparent; }
        .show-list-container::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 10px; }
        .show-list-container::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.2); }

        /* Stats Blocks (progress area) */
        .stats-right-panel { display: flex; gap: 16px; flex-shrink: 0; }
        .glass-box {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 24px; padding: 28px;
            min-width: 140px;
            display: flex; flex-direction: column; justify-content: center; align-items: center;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .glass-box:hover { background: rgba(255, 255, 255, 0.08); }
        .daily-num { font-size: 42px; font-weight: 800; line-height: 1; margin-bottom: 8px; }
        .daily-label { font-size: 11px; color: rgba(255,255,255,0.5); text-transform: uppercase; font-weight: 600; letter-spacing: 1px; }

        .show-title {
            font-size: 16px; font-weight: 600;
            margin-bottom: 14px; padding-bottom: 8px; margin-top: 24px;
            color: rgba(255,255,255,0.9);
            letter-spacing: 0.3px;
        }
        .season-row { display: flex; align-items: flex-start; margin-bottom: 10px; }
        .season-label {
            font-weight: 500; width: 100px;
            color: rgba(255,255,255,0.4); font-size: 13px;
            flex-shrink: 0; padding-top: 8px;
            letter-spacing: 0.3px;
        }
        .ep-wrapper { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; flex: 1; min-width: 0; }

        /* Episode Boxes - refined */
        .ep-box {
            width: 34px; height: 34px;
            background: rgba(255,255,255,0.04);
            display: flex; align-items: center; justify-content: center;
            border-radius: 10px;
            cursor: pointer; font-size: 13px; font-weight: 600;
            border: 1px solid rgba(255,255,255,0.04);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            user-select: none; position: relative;
            touch-action: manipulation;
        }
        .ep-box:hover {
            background: rgba(255,255,255,0.12);
            border-color: rgba(255,255,255,0.1);
            transform: scale(1.08);
            z-index: 999;
            box-shadow: 0 4px 12px rgba(0,0,0,0.2);
        }
        .ep-box.watched {
            background: var(--primary-green);
            border-color: transparent;
            color: #000;
            font-weight: 700;
        }
        .ep-box.dimmed {
            opacity: 0.12;
            filter: blur(0.5px);
        }
        .ep-box.end-ep {
            border: 1.5px solid var(--accent-red);
            background: rgba(255, 69, 58, 0.08);
            box-shadow: 0 0 0 1px rgba(255, 69, 58, 0.1);
        }

        /* Progress Area - refined */
        .progress-wrapper { margin-top: 32px; }
        .progress-container {
            background: rgba(255,255,255,0.03);
            height: 36px; border-radius: 18px;
            overflow: hidden;
            border: 1px solid rgba(255,255,255,0.06);
            position: relative;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.05);
        }
        .progress-bar {
            background: linear-gradient(90deg, rgba(255,255,255,0.95) 0%, rgba(255,255,255,1) 100%);
            height: 100%;
            transition: width 1s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative;
        }
        .progress-bar::after {
            content: ''; position: absolute; inset: 0;
            background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.3) 50%, transparent 100%);
            animation: shimmer 2s infinite;
        }
        @keyframes shimmer {
            0% { transform: translateX(-100%); }
            100% { transform: translateX(100%); }
        }
        .progress-text-overlay {
            position: absolute; width: 100%; text-align: center;
            top: 0; left: 0; line-height: 36px;
            font-size: 14px; font-weight: 700;
            mix-blend-mode: difference;
            z-index: 1;
        }
        .stats-text {
            margin-top: 14px; font-size: 14px;
            color: rgba(255,255,255,0.45); text-align: center;
            font-weight: 500; letter-spacing: 0.2px;
        }

        /* Form Area - refined */
        .form-banner {
            width: var(--banner-width); padding: 40px; box-sizing: border-box;
            margin-top: 48px;
        }
        .form-banner h2 {
            margin-top: 0; margin-bottom: 28px;
            font-size: 24px; font-weight: 700;
            letter-spacing: -0.3px;
        }
        .form-banner label {
            color: rgba(255,255,255,0.5);
            font-weight: 500; font-size: 13px;
            margin-bottom: 10px; display: block;
            letter-spacing: 0.3px; text-transform: uppercase;
        }
        .form-banner input {
            padding: 16px 20px; margin-bottom: 20px; width: 100%;
            box-sizing: border-box;
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 14px;
            background: rgba(255,255,255,0.04);
            color: #fff; font-size: 16px;
            outline: none;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .form-banner input:focus {
            border-color: rgba(255,255,255,0.15);
            background: rgba(255,255,255,0.06);
            box-shadow: 0 0 0 4px rgba(255,255,255,0.03);
        }
        .form-banner button {
            padding: 18px 32px;
            background: #fff; color: #000;
            border: none;
            border-radius: 14px;
            cursor: pointer;
            font-size: 16px; font-weight: 700;
            width: 100%;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            letter-spacing: 0.3px;
        }
        .form-banner button:hover {
            transform: translateY(-2px);
            box-shadow: 0 12px 30px rgba(255,255,255,0.25);
        }

        /* Global Tooltip - refined */
        #global-tooltip {
            position: fixed;
            background: rgba(30, 30, 30, 0.98);
            color: #fff;
            padding: 10px 16px;
            border-radius: 12px;
            white-space: nowrap;
            font-size: 13px; font-weight: 500;
            z-index: 99999;
            opacity: 0; pointer-events: none;
            transition: opacity 0.25s ease, transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            box-shadow: 0 8px 24px rgba(0,0,0,0.3);
            border: 1px solid rgba(255,255,255,0.1);
            transform: translateX(-50%) translateY(10px);
            left: 0; top: 0;
        }
        #global-tooltip.show {
            opacity: 1;
            transform: translateX(-50%) translateY(0);
        }

        /* Settings Icon - refined */
        .settings-btn {
            position: fixed; top: 36px; right: 36px;
            background: rgba(255,255,255,0.12);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 50%;
            width: 48px; height: 48px;
            display: flex; align-items: center; justify-content: center;
            cursor: pointer; z-index: 1000; color: #fff;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .settings-btn:hover {
            background: rgba(255,255,255,0.18);
            transform: rotate(90deg);
        }

        /* Background Menu - refined */
        .bg-menu {
            position: fixed; top: 96px; right: 36px;
            background: rgba(30, 30, 30, 0.85);
            backdrop-filter: blur(30px);
            -webkit-backdrop-filter: blur(30px);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 18px;
            padding: 12px;
            display: none;
            flex-direction: column;
            gap: 8px;
            z-index: 1000;
            box-shadow: 0 16px 40px rgba(0,0,0,0.4);
            animation: menuSlide 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }
        @keyframes menuSlide {
            from { opacity: 0; transform: translateY(-10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .bg-option {
            padding: 12px 20px;
            border-radius: 12px;
            cursor: pointer;
            font-size: 13px; font-weight: 500;
            color: rgba(255,255,255,0.85);
            background: transparent;
            border: none;
            text-align: center;
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .bg-option:hover {
            background: rgba(255,255,255,0.1);
            color: #fff;
            padding-left: 24px;
        }

        /* ===== Mobile Responsive ===== */
        @media (max-width: 768px) {
            :root {
                --banner-width: 100vw;
            }

            body {
                padding: 40px 0;
            }

            .banner-container {
                width: 100vw;
                margin-bottom: 24px;
            }

            .title-banner {
                padding: 28px 20px;
            }
            .title-banner h1 {
                font-size: 32px;
                letter-spacing: -1px;
            }

            /* Target card: full width, less padding */
            .target-card {
                width: 100vw;
                padding: 20px;
                margin-bottom: 24px;
            }

            /* Stack poster above info instead of side-by-side */
            .target-header {
                flex-direction: column;
                height: auto;
                gap: 20px;
            }
            .target-poster {
                width: calc(100% - 24px);
                margin: 0 auto;
                aspect-ratio: 2/3;
                border-radius: 16px;
                object-fit: cover;
            }
            .target-info {
                padding-top: 0;
            }

            /* Title bar: stack title and actions vertically */
            .target-title-bar {
                flex-direction: column;
                align-items: flex-start;
                gap: 12px;
                margin-bottom: 12px;
            }
            .target-info h2 {
                font-size: 22px;
            }

            /* Action group: wrap, smaller gap */
            .action-group {
                flex-wrap: wrap;
                gap: 8px;
                width: 100%;
            }
            .btn {
                line-height: 38px;
                height: 38px;
                padding: 0 14px;
                font-size: 12px;
            }

            /* Inline stats: wrap on small screens */
            .stats-inline-panel {
                flex-wrap: wrap;
                gap: 8px;
            }
            .stats-box {
                height: 34px;
                font-size: 12px;
                line-height: 34px;
                padding: 0 12px;
            }
            .stats-box .num { font-size: 12px; }
            .stats-box .label { font-size: 10px; }

            /* Show list: remove right padding scrollbar area */
            .show-list-container {
                padding-right: 0;
                overflow-y: visible;
                max-height: none;
                -webkit-overflow-scrolling: touch;
            }

            .show-title {
                font-size: 14px;
                margin-top: 16px;
                margin-bottom: 10px;
            }

            /* Season rows: stack label on top of episodes */
            .season-row {
                flex-direction: column;
                margin-bottom: 14px;
            }
            .season-label {
                width: auto;
                padding-top: 0;
                margin-bottom: 6px;
                font-size: 12px;
            }

            /* Episode boxes: slightly smaller for mobile */
            .ep-box {
                width: 30px;
                height: 30px;
                font-size: 11px;
                border-radius: 8px;
            }
            .ep-wrapper {
                gap: 6px;
            }

            /* Progress area */
            .progress-wrapper {
                margin-top: 20px;
            }
            .progress-container {
                height: 28px;
                border-radius: 14px;
            }
            .progress-text-overlay {
                line-height: 28px;
                font-size: 12px;
            }
            .stats-text {
                font-size: 12px;
                margin-top: 10px;
            }

            /* Stats blocks */
            .glass-box {
                padding: 20px;
                min-width: 100px;
                border-radius: 18px;
            }
            .daily-num {
                font-size: 30px;
            }
            .stats-right-panel {
                gap: 10px;
            }

            /* Form */
            .form-banner {
                width: 100vw;
                padding: 24px 20px;
                margin-top: 24px;
            }
            .form-banner h2 {
                font-size: 20px;
                margin-bottom: 20px;
            }
            .form-banner input {
                padding: 14px 16px;
                font-size: 16px; /* prevents iOS zoom */
                border-radius: 12px;
            }
            .form-banner button {
                padding: 16px 24px;
                font-size: 15px;
                border-radius: 12px;
            }

            /* Settings button: smaller, repositioned */
            .settings-btn {
                top: 16px;
                right: 16px;
                width: 40px;
                height: 40px;
            }

            /* Background menu: repositioned */
            .bg-menu {
                top: 66px;
                right: 16px;
                border-radius: 14px;
                padding: 8px;
            }
            .bg-option {
                padding: 10px 16px;
                font-size: 12px;
            }

            /* Tooltip: better mobile positioning */
            #global-tooltip {
                font-size: 12px;
                padding: 8px 12px;
                border-radius: 10px;
            }

            /* Right-click hint: adjust for touch */
            .right-click-hint {
                font-size: 12px;
            }
        }

        @media (max-width: 400px) {
            .title-banner h1 {
                font-size: 26px;
            }
            .target-card {
                padding: 16px;
            }
            .target-info h2 {
                font-size: 18px;
            }
            .btn {
                line-height: 34px;
                height: 34px;
                padding: 0 10px;
                font-size: 11px;
                border-radius: 10px;
            }
            .ep-box {
                width: 28px;
                height: 28px;
                font-size: 10px;
                border-radius: 7px;
            }
            .ep-wrapper {
                gap: 5px;
            }
        }
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

            // Mobile long-press support for setting end episode
            let longPressTimer = null;
            let longPressTarget = null;
            document.querySelectorAll('.ep-box').forEach(box => {
                box.addEventListener('touchstart', (e) => {
                    longPressTarget = box;
                    longPressTimer = setTimeout(() => {
                        e.preventDefault();
                        const epId = box.getAttribute('onclick').match(/toggleEp[(](\\d+)/)[1];
                        setEndEp(e, parseInt(epId));
                        longPressTarget = null;
                    }, 500);
                }, { passive: false });
                box.addEventListener('touchend', () => {
                    clearTimeout(longPressTimer);
                    longPressTarget = null;
                });
                box.addEventListener('touchmove', () => {
                    clearTimeout(longPressTimer);
                    longPressTarget = null;
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
            .then(data => {
                if(data.success) {
                    updateEndEpisode(data.target_id, data.ep_id, data.show_title, data.stats);
                }
            });
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
        function refreshTarget(targetId) {
            const btn = document.querySelector('#card-' + targetId + ' .action-group .btn:first-child');
            if(!btn) return;
            const originalText = btn.innerHTML;
            btn.innerHTML = '...';
            btn.disabled = true;
            fetch('/refresh/' + targetId, { method: 'POST' })
            .then(res => res.json())
            .then(data => { 
                if(data.success) {
                    window.location.reload();
                } else {
                    btn.innerHTML = originalText;
                    btn.disabled = false;
                    alert('Refresh failed');
                }
            })
            .catch(err => {
                console.error(err);
                btn.innerHTML = originalText;
                btn.disabled = false;
                alert('Error refreshing');
            });
        }
        function moveTarget(targetId, direction) {
            const currentCard = document.getElementById('card-' + targetId);
            if (!currentCard) return;
            
            const sibling = direction === 'up' ? currentCard.previousElementSibling : currentCard.nextElementSibling;
            
            if (sibling && sibling.classList.contains('target-card')) {
                const currentRect = currentCard.getBoundingClientRect();
                const siblingRect = sibling.getBoundingClientRect();
                const dy = siblingRect.top - currentRect.top;

                currentCard.style.transition = 'transform 0.4s ease-in-out, box-shadow 0.4s ease-in-out';
                currentCard.style.zIndex = '100';
                currentCard.style.position = 'relative';
                
                sibling.style.transition = 'transform 0.4s ease-in-out';
                sibling.style.position = 'relative';

                requestAnimationFrame(() => {
                    currentCard.style.transform = `translateY(${dy}px) scale(1.02)`;
                    currentCard.style.boxShadow = '0 25px 50px rgba(0,0,0,0.6)';
                    sibling.style.transform = `translateY(${-dy}px)`;
                });

                setTimeout(() => {
                    // Reset styles
                    currentCard.style.transition = '';
                    currentCard.style.transform = '';
                    currentCard.style.boxShadow = '';
                    currentCard.style.zIndex = '';
                    currentCard.style.position = '';
                    
                    sibling.style.transition = '';
                    sibling.style.transform = '';
                    sibling.style.position = '';

                    // Swap in DOM
                    if (direction === 'up') {
                        sibling.parentNode.insertBefore(currentCard, sibling);
                    } else {
                        sibling.parentNode.insertBefore(sibling, currentCard);
                    }

                    // Update backend silently
                    fetch('/move/' + targetId + '/' + direction, { method: 'POST' });
                }, 400);
            } else {
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
                if (stats.daily_mins != null) daily.innerHTML = '<span class="num">' + stats.daily_mins + '</span><span class="label">min/day</span>';
                else daily.innerHTML = '<span class="label">No Goal</span>';
            }
        }
        function updateEndEpisode(targetId, newEndEpId, showTitle, stats) {
            const card = document.getElementById('card-' + targetId);
            if(!card) return;

            // Find the show section by matching the show title
            const newEndBox = card.querySelector('.ep-box[onclick*="' + newEndEpId + '"]');
            if(!newEndBox) return;

            // Get the show section containing this episode
            const showSection = newEndBox.closest('.show-section');
            if(showSection) {
                // Remove end-ep class from all episodes in this show
                showSection.querySelectorAll('.ep-box.end-ep').forEach(box => box.classList.remove('end-ep'));
            }

            // Add end-ep class to new end episode
            newEndBox.classList.add('end-ep');

            // Update dimmed state only for episodes after the end point within the same show
            if(showSection) {
                // Get all ep-boxes in this show section in order
                const allEpsInShow = Array.from(showSection.querySelectorAll('.ep-box'));
                const endIndex = allEpsInShow.indexOf(newEndBox);
                allEpsInShow.forEach((box, idx) => {
                    if(idx > endIndex) {
                        box.classList.add('dimmed');
                    } else {
                        box.classList.remove('dimmed');
                    }
                });
            }

            // Update stats
            updateStats(targetId, stats);
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
                        <button class="btn" onclick="refreshTarget({{ target.id }})" title="Refresh Data">↻</button>
                        <button class="btn" onclick="moveTarget({{ target.id }}, 'up')" title="Move Up">▲</button>
                        <button class="btn" onclick="moveTarget({{ target.id }}, 'down')" title="Move Down">▼</button>
                        <button class="btn delete-btn" onclick="deleteTarget({{ target.id }})" title="Delete Target">Delete</button>

                        <div class="stats-inline-panel">
                            <div class="stats-box" id="daily-{{ target.id }}">
                                {% if target.stats.daily_mins != null %}
                                    <span class="num">{{ target.stats.daily_mins }}</span><span class="label">min/day</span>
                                {% else %}
                                    <span class="label">No Goal</span>
                                {% endif %}
                            </div>

                            {% if target.end_date %}
                            <div class="stats-box" style="background: rgba(255,255,255,0.05);">
                                <span class="num">{{ target.end_date[5:] }}</span><span class="label" style="color: var(--primary-blue);">deadline</span>
                            </div>
                            {% endif %}
                        </div>
                    </div>
                </div>
                <p style="margin: 0 0 20px 0; color: rgba(255,255,255,0.4); font-size: 14px;">Right-click or long-press an episode to set binge end point.</p>

                <div class="show-list-container">
                    {% for show_title, seasons in target.shows.items() %}
                    <div class="show-section">
                        <div class="show-title">{{ show_title }}</div>
                        {% set show_end_ep_id = target.stats.end_eps_by_show.get(show_title) %}
                        {% set is_after_end = namespace(value=false) %}
                        {% for season_num, eps in seasons.items() %}
                        <div class="season-row">
                            <div class="season-label">Season {{ season_num }}</div>
                            <div class="ep-wrapper">
                                {% for ep in eps %}
                                    {% if show_end_ep_id and ep.id > show_end_ep_id %}
                                        {% set is_after_end.value = true %}
                                    {% else %}
                                        {% set is_after_end.value = false %}
                                    {% endif %}
                                    <div class="ep-box {% if ep.watched %}watched{% endif %} {% if show_end_ep_id == ep.id %}end-ep{% endif %} {% if is_after_end.value %}dimmed{% endif %}" 
                                         onclick="toggleEp({{ ep.id }}, this)"
                                         oncontextmenu="setEndEp(event, {{ ep.id }})"
                                         data-tooltip="Ep {{ ep.episode }}: {{ ep.title }} ({{ ep.runtime_minutes }}m)">
                                        {{ ep.episode }}
                                    </div>
                                {% endfor %}
                            </div>
                        </div>
                        {% endfor %}
                    </div>
                    {% endfor %}
                </div>
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

    <div class="form-banner glass-panel" style="order: 9999;">
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
