import os
import sys
import time
import logging
import requests
import math
import hashlib
import json
import base64
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from collections import Counter
from datetime import datetime, timedelta

# Set up clean terminal logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TOKEN = os.getenv('GH_PAT')
USERNAME = os.getenv('GH_USERNAME')
# Pull the highly secure salt from GitHub Secrets
SECRET_SALT = os.getenv('CACHE_SALT', 'default_fallback_do_not_use')
CACHE_FILE = 'repo_cache.json'

if not TOKEN or not USERNAME:
    logging.error("FATAL: GH_PAT or GH_USERNAME environment variables are missing.")
    sys.exit(1)

if SECRET_SALT == 'default_fallback_do_not_use':
    logging.warning("WARNING: CACHE_SALT secret not found. Using an insecure fallback hash. Please add CACHE_SALT to your GitHub Secrets.")

def xor_crypt(data_bytes, key_str):
    """Scrambles or unscrambles binary data using the secret salt."""
    key_bytes = key_str.encode('utf-8')
    if not key_bytes:
        key_bytes = b'default_fallback'
    key_len = len(key_bytes)
    return bytes(b ^ key_bytes[i % key_len] for i, b in enumerate(data_bytes))

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'rb') as f:
                encoded_b64 = f.read()
            # If the file is empty, return empty cache
            if not encoded_b64.strip():
                return {}
            # Decode Base64 back to scrambled bytes
            encrypted_bytes = base64.b64decode(encoded_b64)
            # Unscramble bytes back to JSON text
            json_bytes = xor_crypt(encrypted_bytes, SECRET_SALT)
            return json.loads(json_bytes.decode('utf-8'))
        except Exception as e:
            logging.warning("Cache file unreadable or encryption key changed. Starting fresh.")
            return {}
    return {}

def save_cache(cache_data):
    try:
        # Convert data to JSON string, then to bytes
        json_bytes = json.dumps(cache_data).encode('utf-8')
        # Scramble the bytes using the secret salt
        encrypted_bytes = xor_crypt(json_bytes, SECRET_SALT)
        # Encode to Base64 so it can be safely saved as text
        encoded_b64 = base64.b64encode(encrypted_bytes)
        with open(CACHE_FILE, 'wb') as f:
            f.write(encoded_b64)
    except Exception as e:
        logging.error("Failed to save encrypted cache.")

# Configure a robust requests session with automatic retries for basic connection drops
session = requests.Session()
retry_strategy = Retry(
    total=5,
    backoff_factor=2,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("https://", adapter)
session.mount("http://", adapter)
session.headers.update({'Authorization': f'token {TOKEN}', 'Accept': 'application/vnd.github.v3+json'})

def handle_rate_limit(response):
    """Checks for GitHub API rate limits and automatically sleeps until reset."""
    if response.status_code in [403, 429] and 'X-RateLimit-Remaining' in response.headers:
        if response.headers.get('X-RateLimit-Remaining') == '0':
            reset_time = int(response.headers.get('X-RateLimit-Reset', time.time() + 60))
            sleep_duration = max(reset_time - time.time(), 0) + 1
            logging.warning(f"Rate limit exceeded. Sleeping for {sleep_duration:.0f} seconds.")
            time.sleep(sleep_duration)
            return True
    return False

def get_member_since():
    logging.info("Fetching GitHub account creation date...")
    try:
        res = session.get(f'https://api.github.com/users/{USERNAME}', timeout=15)
        handle_rate_limit(res)
        res.raise_for_status()
        raw_date = res.json().get('created_at', '2020-01-01T00:00:00Z')
        
        # Parse UTC time and calculate IST (UTC + 5:30)
        dt_utc = datetime.strptime(raw_date, "%Y-%m-%dT%H:%M:%SZ")
        dt_ist = dt_utc + timedelta(hours=5, minutes=30)
        
        # Restored to the full, non-compact date format requested by the user
        date_str = dt_utc.strftime("%B %d, %Y")
        time_utc = dt_utc.strftime("%H:%M UTC")
        time_ist = dt_ist.strftime("%H:%M IST")
        
        return f"{date_str} at {time_utc} ({time_ist})"
    except requests.exceptions.RequestException:
        # SECURED: Stripped the exception variable `e` to prevent URL leakage
        logging.error("Failed to fetch user profile. Details masked for security.")
        return "Unknown"

def get_total_commits():
    logging.info("Fetching total lifetime commits...")
    url = f'https://api.github.com/search/commits?q=author:{USERNAME}'
    try:
        res = session.get(url, timeout=15)
        handle_rate_limit(res)
        res.raise_for_status()
        return res.json().get('total_count', 0)
    except requests.exceptions.RequestException:
        logging.error("Failed to fetch total commits. Details masked for security.")
        return 0

def get_total_contributions():
    logging.info("Fetching total graph contributions via GraphQL...")
    query = """
    query($login: String!) {
      user(login: $login) {
        contributionsCollection {
          contributionCalendar {
            totalContributions
          }
        }
      }
    }
    """
    try:
        res = session.post('https://api.github.com/graphql', json={'query': query, 'variables': {"login": USERNAME}}, timeout=15)
        handle_rate_limit(res)
        res.raise_for_status()
        data = res.json()
        if 'errors' in data:
            logging.error("GraphQL errors occurred. Details masked for security.")
            return 0
        return data['data']['user']['contributionsCollection']['contributionCalendar']['totalContributions']
    except (requests.exceptions.RequestException, KeyError):
        logging.error("Failed to fetch total contributions. Details masked for security.")
        return 0

def get_lifetime_repo_stats():
    logging.info("Fetching repository list...")
    try:
        repos_response = session.get(f'https://api.github.com/user/repos?per_page=100&affiliation=owner', timeout=15)
        handle_rate_limit(repos_response)
        repos_response.raise_for_status()
        repos = repos_response.json()
    except requests.exceptions.RequestException:
        logging.error("Failed to fetch repositories. Details masked for security.")
        return 0, 0, [], 0

    cache = load_cache()
    total_loc = 0
    repo_count = 0
    total_size_kb = 0
    language_bytes = Counter()

    for repo in repos:
        if repo.get('fork'): 
            continue
        
        repo_name = repo['name']
        pushed_at = repo.get('pushed_at')
        
        repo_count += 1
        total_size_kb += repo.get('size', 0)

        # SECURED: Anonymize the display name in the console logs completely
        display_name = f"Repository #{repo_count}"
        
        # SECURED: Cryptographically salt the hash with the hidden GitHub Secret
        salt_string = f"{repo_name}_{SECRET_SALT}"
        repo_hash = hashlib.sha256(salt_string.encode('utf-8')).hexdigest()

        # --- SMART CACHE CHECK (Using the Secret Salted Hash) ---
        if repo_hash in cache and cache[repo_hash].get('pushed_at') == pushed_at:
            logging.info(f"[{display_name}] No recent changes. Loaded instantly from cache.")
            total_loc += cache[repo_hash].get('loc', 0)
            for lang, bytes_cnt in cache[repo_hash].get('languages', {}).items():
                language_bytes[lang] += bytes_cnt
            continue
            
        logging.info(f"[{display_name}] Changes detected (or new repo). Fetching fresh data from GitHub...")
        
        repo_langs = {}
        # 1. Fetch exact byte count for languages
        lang_url = f"https://api.github.com/repos/{USERNAME}/{repo_name}/languages"
        for _ in range(5):
            try:
                lang_res = session.get(lang_url, timeout=10)
                if not handle_rate_limit(lang_res) and lang_res.status_code == 200:
                    repo_langs = lang_res.json()
                    for lang, bytes_cnt in repo_langs.items():
                        language_bytes[lang] += bytes_cnt
                    break
            except requests.exceptions.RequestException:
                time.sleep(2)

        # 2. Fetch contributor line additions
        repo_loc = 0
        contrib_url = f"https://api.github.com/repos/{USERNAME}/{repo_name}/stats/contributors"
        max_retries = 10
        for attempt in range(max_retries):
            try:
                response = session.get(contrib_url, timeout=15)
                if handle_rate_limit(response): 
                    continue 
                if response.status_code == 200:
                    stats = response.json()
                    if isinstance(stats, list): 
                        for s in stats:
                            if s.get('author') and s['author']['login'].lower() == USERNAME.lower():
                                for week in s.get('weeks', []):
                                    repo_loc += week.get('a', 0)
                    logging.info(f"[{display_name}] Stats & Languages tallied.")
                    break 
                elif response.status_code == 202:
                    sleep_time = 2 * (2 ** attempt)
                    logging.info(f"[{display_name}] GitHub computing. Retrying in {sleep_time}s (Attempt {attempt + 1}/{max_retries})...")
                    time.sleep(sleep_time)
                elif response.status_code == 204:
                    break
                else:
                    break
            except requests.exceptions.RequestException:
                time.sleep(5)
        else:
            logging.error(f"[{display_name}] FATAL: Failed to fetch stats after {max_retries} attempts.")

        total_loc += repo_loc

        # Update the cache using the secure salted hash as the key
        cache[repo_hash] = {
            'pushed_at': pushed_at,
            'loc': repo_loc,
            'languages': repo_langs
        }
        save_cache(cache)

    # Calculate exact percentages and group micro-languages
    total_bytes_all_repos = sum(language_bytes.values())
    lang_stats = []
    other_pct = 0.0
    other_langs = []

    if total_bytes_all_repos > 0:
        for lang, byte_count in language_bytes.most_common():
            pct = (byte_count / total_bytes_all_repos) * 100
            
            # If it rounds to 0.1% or higher, keep it main
            if pct >= 0.05: 
                lang_stats.append({"name": lang, "pct": pct, "is_other": False})
            # If it rounds to 0.0%, throw it in the 'Other' bucket
            else:
                other_pct += pct
                other_langs.append(lang)
        
        # Build the dynamic "Other" label
        if other_langs:
            if len(other_langs) > 3:
                other_name = f"Other ({', '.join(other_langs[:3])}, etc)"
            else:
                other_name = f"Other ({', '.join(other_langs)})"
            
            lang_stats.append({"name": other_name, "pct": other_pct, "is_other": True})
    else:
        lang_stats = [{"name": "None", "pct": 100, "is_other": False}]

    total_size_mb = total_size_kb / 1024
    return repo_count, total_loc, lang_stats, total_size_mb

def get_language_color(lang):
    if lang.startswith("Other"): return "#858585"
    colors = {
        "Python": "#3572A5", "HTML": "#e34c26", "JavaScript": "#f1e05a", "CSS": "#563d7c", 
        "TypeScript": "#3178c6", "Java": "#b07219", "C++": "#f34b7d", "C": "#555555", 
        "C#": "#178600", "PHP": "#4F5D95", "Go": "#00ADD8", "Rust": "#dea584", 
        "Ruby": "#701516", "Dart": "#00B4AB", "Kotlin": "#A97BFF", "Swift": "#F05138", 
        "Jupyter Notebook": "#DA5B0B", "Shell": "#89e051", "Vue": "#41b883", "SCSS": "#c6538c",
        "PLpgSQL": "#336790", "Dockerfile": "#384d54"
    }
    if lang in colors: 
        return colors[lang]
    hash_val = int(hashlib.md5(lang.encode('utf-8')).hexdigest(), 16)
    return f"#{hash_val & 0xFFFFFF:06x}"

def generate_svg(repos, commits, contribs, loc, lang_stats, size_mb, full_date):
    logging.info("Generating SVG file...")
    
    # Calculate the current time to stamp on the card
    now_utc = datetime.utcnow()
    now_ist = now_utc + timedelta(hours=5, minutes=30)
    last_updated_str = now_ist.strftime("%B %d, %Y at %H:%M IST")

    svg_width = 630
    bar_width = 520
    
    bar_svg = ""
    legend_svg = ""
    bar_x = 0

    for idx, lang in enumerate(lang_stats):
        color = get_language_color(lang['name'])
        width = (lang['pct'] / 100) * bar_width 
        
        if width > 0.5:
            bar_svg += f'<rect x="{bar_x}" y="0" width="{width}" height="12" fill="{color}" />\n'
            bar_x += width

        col = idx % 2
        row = idx // 2
        lx = col * 240
        ly = 35 + (row * 24)

        if lang.get('is_other'):
            label_text = lang["name"]
        else:
            label_text = f"{lang['name']} {lang['pct']:.1f}%"

        legend_svg += f'<circle cx="{lx + 5}" cy="{ly}" r="5" fill="{color}" />\n'
        legend_svg += f'<text x="{lx + 15}" y="{ly + 4}" font-size="13" font-weight="600" fill="#c9d1d9">{label_text}</text>\n'

    num_rows = math.ceil(len(lang_stats) / 2)
    legend_height = num_rows * 24
    
    svg_height = 350 + legend_height 
    font_family = "'Segoe UI', Ubuntu, Sans-Serif, 'Apple Color Emoji', 'Segoe UI Emoji', 'Segoe UI Symbol', 'Noto Color Emoji'"

    svg = f"""<svg width="{svg_width}" height="{svg_height}" viewBox="0 0 {svg_width} {svg_height}" fill="none" xmlns="http://www.w3.org/2000/svg">
  <style>
    .header {{ font: 700 20px {font_family}; fill: #58a6ff; animation: fadeIn 0.8s ease-in-out; }}
    .stat {{ font: 600 16px {font_family}; fill: #c9d1d9; }}
    .bold {{ font-weight: 800; fill: #ffffff; }}
    .fork-note {{ font: italic 11px {font_family}; fill: #6e7681; }}
    text {{ font-family: {font_family}; }}
    @keyframes fadeIn {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
    @keyframes float {{ 0% {{ transform: translateY(0px); }} 50% {{ transform: translateY(-5px); }} 100% {{ transform: translateY(0px); }} }}
    .floating {{ animation: float 3s ease-in-out infinite; }}
  </style>
  <rect width="{svg_width - 2}" height="{svg_height - 2}" x="1" y="1" rx="15" fill="#0d1117" stroke="#30363d" stroke-width="2" />
  <g class="floating">
    <text x="25" y="45" class="header">{USERNAME}'s Digital Footprint</text>
  </g>
  <g transform="translate(25, 80)">
    <text x="0" y="0" class="stat">📦 Total Repositories: <tspan class="bold">{repos}</tspan></text>
    <text x="0" y="30" class="stat">🗓️ Member Since: <tspan class="bold">{full_date}</tspan></text>
    <text x="0" y="60" class="stat">🔥 Lifetime Commits: <tspan class="bold">{commits:,}</tspan></text>
    <text x="0" y="90" class="stat">✨ Total Contributions: <tspan class="bold">{contribs:,}</tspan></text>
    <text x="0" y="120" class="stat">💾 Total Codebase Size: <tspan class="bold">{size_mb:.1f} MB</tspan></text>
    
    <text x="0" y="160" class="stat" fill="#79c0ff">💻 Lines of Code files Authored: <tspan class="bold" fill="#79c0ff">{loc:,}</tspan></text>

    <text x="0" y="200" class="stat">🏆 Comprehensive Language Breakdown</text>
    <g transform="translate(0, 220)">
        <clipPath id="bar-clip">
            <rect x="0" y="0" width="{bar_width}" height="12" rx="6" />
        </clipPath>
        <g clip-path="url(#bar-clip)">
            {bar_svg}
        </g>
        {legend_svg}
    </g>
  </g>
  <line x1="25" y1="{svg_height - 40}" x2="{svg_width - 25}" y2="{svg_height - 40}" stroke="#30363d" stroke-width="1" />
  <text x="25" y="{svg_height - 15}" class="fork-note">* This data excludes forks and includes all private activity</text>
  <text x="{svg_width - 25}" y="{svg_height - 15}" class="fork-note" text-anchor="end">Last Updated: {last_updated_str}</text>
</svg>"""
    try:
        with open('github_stats.svg', 'w', encoding='utf-8') as f: 
            f.write(svg)
        logging.info("Successfully wrote github_stats.svg")
    except IOError:
        logging.error("Failed to write SVG file. Details masked for security.")

if __name__ == "__main__":
    logging.info("Starting GitHub Stats Generation...")
    commits = get_total_commits()
    contribs = get_total_contributions()
    full_date = get_member_since()
    repos, loc, lang_stats, size_mb = get_lifetime_repo_stats()
    
    if repos > 0 or loc > 0:
        generate_svg(repos, commits, contribs, loc, lang_stats, size_mb, full_date)
        logging.info("Job complete.")
    else:
        logging.error("Failed to retrieve repository data. Aborting SVG generation.")
        sys.exit(1)

