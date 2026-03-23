import requests
import urllib3
import warnings
from datetime import datetime

# Mute proxy warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

class BingeTracker:
    def __init__(self, show_ids):
        self.show_ids = show_ids
        self.episodes = []
        self.main_poster_url = None
        self.total_runtime_seconds = 0
        
    def fetch_data(self):
        if not self.show_ids:
            return

        # 1. Fetch main poster from the first show
        first_show_id = self.show_ids[0]
        try:
            res = requests.get(f"https://api.imdbapi.dev/titles/{first_show_id}", verify=False)
            if res.status_code == 200:
                data = res.json()
                if 'primaryImage' in data and data['primaryImage']:
                    self.main_poster_url = data['primaryImage'].get('url')
        except Exception as e:
            print(f"Error fetching poster: {e}")

        # 2. Fetch episodes for all shows
        for show_id in self.show_ids:
            print(f"Fetching episodes for {show_id}...")
            page_token = None
            while True:
                url = f"https://api.imdbapi.dev/titles/{show_id}/episodes?pageSize=50"
                if page_token:
                    url += f"&pageToken={page_token}"
                
                try:
                    res = requests.get(url, verify=False)
                    if res.status_code != 200:
                        break
                    
                    data = res.json()
                    eps = data.get('episodes', data) if isinstance(data, dict) else data
                    if not eps:
                        break
                        
                    for ep in eps:
                        self.episodes.append({
                            'show_id': show_id,
                            'season': ep.get('season'),
                            'episode': ep.get('episodeNumber'),
                            'title': ep.get('title', 'Unknown Title'),
                            'runtime_seconds': ep.get('runtimeSeconds') or 0
                        })
                        
                    page_token = data.get('nextPageToken')
                    if not page_token:
                        break
                except Exception as e:
                    print(f"Error fetching episodes for {show_id}: {e}")
                    break

    def calculate_progress(self, end_date_str, watched_seconds=0, end_episodes=None):
        """
        end_episodes: dict mapping show_id -> (season, episode) to stop at. 
                      If not provided for a show, includes all episodes.
        """
        total_seconds = 0
        filtered_episodes = []
        
        for ep in self.episodes:
            show_id = ep['show_id']
            # Check if we should include this episode based on end_episodes cutoff
            if end_episodes and show_id in end_episodes:
                end_s, end_e = end_episodes[show_id]
                s = ep['season']
                e = ep['episode']
                
                # Assume season and episode are integers
                try:
                    s = int(s)
                    e = int(e)
                    if s > end_s or (s == end_s and e > end_e):
                        continue # Skip episodes after the end_episode
                except (ValueError, TypeError):
                    pass # Include episodes with unknown/unparseable season/episode
                    
            filtered_episodes.append(ep)
            total_seconds += ep['runtime_seconds']
            
        self.total_runtime_seconds = total_seconds
        
        # Calculate days until end date
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        today = datetime.now().date()
        days_left = (end_date - today).days
        
        if days_left <= 0:
            days_left = 1 # Avoid division by zero, assuming at least 1 day left
            
        remaining_seconds = max(0, total_seconds - watched_seconds)
        minutes_per_day = (remaining_seconds / 60) / days_left
        
        progress_percent = (watched_seconds / total_seconds * 100) if total_seconds > 0 else 0
        
        return {
            "total_minutes": total_seconds // 60,
            "watched_minutes": watched_seconds // 60,
            "remaining_minutes": remaining_seconds // 60,
            "days_left": days_left,
            "minutes_per_day": round(minutes_per_day, 1),
            "progress_percent": round(progress_percent, 2),
            "main_poster": self.main_poster_url,
            "episodes_counted": len(filtered_episodes)
        }

if __name__ == "__main__":
    # Example usage based on user request
    shows = ["tt3322312", "tt18923754"]
    print(f"Tracking shows: {shows}")
    
    tracker = BingeTracker(shows)
    tracker.fetch_data()
    
    # Example: Cut-off for Daredevil (tt3322312) at season 3, episode 13.
    # Daredevil: Born Again (tt18923754) up to season 1, episode 9.
    end_eps = {
        "tt3322312": (3, 13),
        "tt18923754": (1, 9)
    }
    
    # Assume 10 episodes watched so far, average 50 minutes each = 500 minutes (30,000 seconds)
    watched_sec = 30000 
    
    # Let's pick an end date 30 days from now for testing.
    from datetime import timedelta
    future_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    
    stats = tracker.calculate_progress(future_date, watched_seconds=watched_sec, end_episodes=end_eps)
    
    print("\n" + "="*50)
    print("BINGE TRACKER STATS")
    print("="*50)
    print(f"Main Poster URL: {stats['main_poster']}")
    print(f"Episodes Counted: {stats['episodes_counted']}")
    print(f"Total Minutes to Watch: {stats['total_minutes']} minutes")
    print(f"Watched Minutes: {stats['watched_minutes']} minutes")
    print(f"Remaining Minutes: {stats['remaining_minutes']} minutes")
    print(f"Days Left (Target: {future_date}): {stats['days_left']} days")
    print(f"Required Pace: {stats['minutes_per_day']} minutes/day")
    print(f"Overall Binge Progress: {stats['progress_percent']}%")
    print("="*50)
