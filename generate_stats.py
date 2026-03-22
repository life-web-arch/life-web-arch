import os
import requests
import time

TOKEN = os.getenv('GH_PAT')
USERNAME = os.getenv('GH_USERNAME')
headers = {'Authorization': f'token {TOKEN}', 'Accept': 'application/vnd.github.v3+json'}

def get_total_commits():
    # Search API is the most accurate for absolute total commits
    url = f'https://api.github.com/search/commits?q=author:{USERNAME}'
    res = requests.get(url, headers=headers).json()
    return res.get('total_count', 0)

def get_total_contributions():
    # GraphQL for the "Green Square" count (1,221+)
    query = "query($login: String!) { user(login: $login) { contributionsCollection { contributionCalendar { totalContributions } } } }"
    res = requests.post('https://api.github.com/graphql', json={'query': query, 'variables': {"login": USERNAME}}, headers={"Authorization": f"Bearer {TOKEN}"})
    return res.json()['data']['user']['contributionsCollection']['contributionCalendar']['totalContributions']

def get_lifetime_repo_stats():
    repos = requests.get(f'https://api.github.com/user/repos?per_page=100&affiliation=owner', headers=headers).json()
    total_loc = 0
    repo_count = 0
    for repo in repos:
        if repo.get('fork'): continue
        repo_count += 1
        url = f"https://api.github.com/repos/{USERNAME}/{repo['name']}/stats/contributors"
        response = requests.get(url, headers=headers)
        retries = 0
        while response.status_code == 202 and retries < 5:
            time.sleep(3)
            response = requests.get(url, headers=headers)
            retries += 1
        if response.status_code == 200:
            stats = response.json()
            for s in stats:
                if s['author']['login'].lower() == USERNAME.lower():
                    for week in s['weeks']:
                        total_loc += week['a']
    return repo_count, total_loc

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
        <text x="0" y="60" class="stat">✨ Total Contributions: <tspan class="bold">{contribs:,}</tspan></text>
        <text x="0" y="95" class="stat" fill="#79c0ff">💻 Lines of Code Authored: <tspan class="bold" fill="#79c0ff">{loc:,}</tspan></text>
      </g>
      <line x1="25" y1="210" x2="425" y2="210" stroke="#30363d" stroke-width="1" />
      <text x="25" y="235" class="fork-note">* This data excludes forks and includes all private activity</text>
    </svg>
    """
    with open('github_stats.svg', 'w') as f: f.write(svg)

if __name__ == "__main__":
    print("Fetching high-accuracy lifetime stats...")
    commits = get_total_commits()
    contribs = get_total_contributions()
    repos, loc = get_lifetime_repo_stats()
    generate_svg(repos, commits, contribs, loc)
    print(f"Success! Found {commits} commits.")
