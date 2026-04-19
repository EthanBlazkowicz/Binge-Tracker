import sqlite3
import requests
import math
import os
from datetime import datetime
from flask import Flask, request, jsonify, render_template, redirect, url_for

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

    return render_template('index.html', targets=targets)

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


if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000, host='0.0.0.0')
