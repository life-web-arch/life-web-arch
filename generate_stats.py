import os
import time
import requests

TOKEN = os.getenv('GH_PAT')
USERNAME = os.getenv('GH_USERNAME')

headers = {
    'Authorization': f'token {TOKEN}',
    'Accept': 'application/vnd.github.v3+json'
}

def get_repos():
    repos =[]
    page = 1
    while True:
        url = f'https://api.github.com/user/repos?per_page=100&page={page}&affiliation=owner'
        response = requests.get(url, headers=headers).json()
        if not response:
            break
        repos.extend(response)
        page += 1
    return repos

def calculate_stats(repos):
    total_commits = 0
    lines_written = 0
    
    for repo in repos:
        # Skip forks to only count your original work
        if repo.get('fork'):
            continue
            
        repo_name = repo['name']
        owner = repo['owner']['login']
        url = f'https://api.github.com/repos/{owner}/{repo_name}/stats/contributors'
        
        # Fetch stats, handling GitHub's 202 Accepted background processing status
        response = requests.get(url, headers=headers)
        if response.status_code == 202:
            time.sleep(2)
            response = requests.get(url, headers=headers)
            
        if response.status_code == 200:
            stats = response.json()
            for user_stat in stats:
                if user_stat['author']['login'].lower() == USERNAME.lower():
                    total_commits += user_stat['total']
                    for week in user_stat['weeks']:
                        lines_written += week['a']
                        
    return total_commits, lines_written

def generate_svg(repos_count, commits, loc):
    svg_template = f"""<svg width="400" height="180" xmlns="http://www.w3.org/2000/svg">
      <rect width="100%" height="100%" fill="#0d1117" rx="10"/>
      <rect width="100%" height="100%" fill="none" rx="10" stroke="#30363d" stroke-width="2"/>
      <text x="20" y="40" fill="#58a6ff" font-family="Arial" font-size="20" font-weight="bold">{USERNAME}'s GitHub Stats</text>
      <text x="20" y="85" fill="#c9d1d9" font-family="Arial" font-size="16">📦 Total Repositories: {repos_count}</text>
      <text x="20" y="120" fill="#c9d1d9" font-family="Arial" font-size="16">🔥 Total Commits: {commits:,}</text>
      <text x="20" y="155" fill="#c9d1d9" font-family="Arial" font-size="16">💻 Lines of Code Written: {loc:,}</text>
    </svg>"""
    
    with open('github_stats.svg', 'w') as f:
        f.write(svg_template)

if __name__ == "__main__":
    print(f"Fetching stats for {USERNAME}...")
    my_repos = get_repos()
    original_repos =[r for r in my_repos if not r.get('fork')]
    commits, loc = calculate_stats(original_repos)
    generate_svg(len(original_repos), commits, loc)
    print("SVG successfully generated!")
