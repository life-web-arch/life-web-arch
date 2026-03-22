import os
import requests
import time
from datetime import datetime

TOKEN = os.getenv('GH_PAT')
USERNAME = os.getenv('GH_USERNAME')
headers = {'Authorization': f'token {TOKEN}', 'Accept': 'application/vnd.github.v3+json'}

def get_lifetime_contributions():
    # 1. First, find out when you joined GitHub
    user_query = "query($login: String!) { user(login: $login) { createdAt } }"
    user_data = requests.post('https://api.github.com/graphql', 
        json={'query': user_query, 'variables': {"login": USERNAME}}, 
        headers={"Authorization": f"Bearer {TOKEN}"}).json()
    
    join_date = user_data['data']['user']['createdAt']
    
    # 2. Query contributions from your join date until NOW
    query = """
    query($login: String!, $from: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from) {
          contributionCalendar { totalContributions }
        }
      }
    }
    """
    res = requests.post('https://api.github.com/graphql', 
        json={'query': query, 'variables': {"login": USERNAME, "from": join_date}}, 
        headers={"Authorization": f"Bearer {TOKEN}"})
    return res.json()['data']['user']['contributionsCollection']['contributionCalendar']['totalContributions']

def get_lifetime_repo_stats():
    # Fetch ALL owner repositories
    repos = requests.get(f'https://api.github.com/user/repos?per_page=100&affiliation=owner', headers=headers).json()
    total_commits = 0
    total_loc = 0
    repo_count = 0
    
    for repo in repos:
        if repo.get('fork'): continue
        repo_count += 1
        name = repo['name']
        url = f"https://api.github.com/repos/{USERNAME}/{name}/stats/contributors"
        
        # Patient retry logic for deep history calculation
        response = requests.get(url, headers=headers)
        retries = 0
        while response.status_code == 202 and retries < 5:
            time.sleep(3)
            response = requests.get(url, headers=headers)
            retries += 1
            
        if response.status_code == 200:
            stats = response.json()
            if stats:
                for s in stats:
                    if s['author']['login'].lower() == USERNAME.lower():
                        total_commits += s['total']
                        for week in s['weeks']:
                            total_loc += week['a']
    return repo_count, total_commits, total_loc

def generate_svg(repos, commits, contribs, loc):
    svg = f"""
    <svg width="450" height="260" viewBox="0 0 450 260" fill="none" xmlns="http://www.w3.org/2000/svg">
      <style>
        .header {{ font: 700 20px 'Segoe UI', Ubuntu, Sans-Serif; fill: #58a6ff; animation: fadeIn 0.8s ease-in-out; }}
        .stat {{ font: 600 16px 'Segoe UI', Ubuntu, Sans-Serif; fill: #c9d1d9; }}
        .bold {{ font-weight: 800; fill: #ffffff; }}
        .fork-note {{ font: italic 11px 'Segoe UI', Ubuntu, Sans-Serif; fill: #6e7681; }}
        @keyframes fadeIn {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
        @keyframes float {{ 0% {{ transform: translateY(0px); }} 50% {{ transform: translateY(-5px); }} 100% {{ transform: translateY(0px); }} }}
        .floating {{ animation: float 3s ease-in-out infinite; }}
      </style>
      <rect width="448" height="258" x="1" y="1" rx="15" fill="#0d1117" stroke="#30363d" stroke-width="2" />
      <g class="floating">
        <text x="25" y="45" class="header">{USERNAME}'s Digital Footprint</text>
      </g>
      <g transform="translate(25, 85)">
        <text x="0" y="0" class="stat">📦 Total Repositories: <tspan class="bold">{repos}</tspan></text>
        <text x="0" y="30" class="stat">🔥 Lifetime Commits: <tspan class="bold">{commits:,}</tspan></text>
        <text x="0" y="60" class="stat">✨ Lifetime Contributions: <tspan class="bold">{contribs:,}</tspan></text>
        <text x="0" y="95" class="stat" fill="#79c0ff">💻 Lifetime Lines of Code: <tspan class="bold" fill="#79c0ff">{loc:,}</tspan></text>
      </g>
      <line x1="25" y1="210" x2="425" y2="210" stroke="#30363d" stroke-width="1" />
      <text x="25" y="235" class="fork-note">* Data covers your entire GitHub history (forks excluded)</text>
    </svg>
    """
    with open('github_stats.svg', 'w') as f: f.write(svg)

if __name__ == "__main__":
    print("Calculating full lifetime statistics...")
    contribs = get_lifetime_contributions()
    repos, commits, loc = get_lifetime_repo_stats()
    generate_svg(repos, commits, contribs, loc)
    print("Success! Lifetime stats calculated.")
