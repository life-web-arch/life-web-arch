import os
import requests

TOKEN = os.getenv('GH_PAT')
USERNAME = os.getenv('GH_USERNAME')

def query_graphql(query, variables):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    request = requests.post('https://api.github.com/graphql', json={'query': query, 'variables': variables}, headers=headers)
    return request.json()

def get_stats():
    # This query fetches Total Contributions (Commits + PRs + Issues) and Repo count
    query = """
    query($login: String!) {
      user(login: $login) {
        repositories(ownerAffiliations: OWNER) {
          totalCount
        }
        contributionsCollection {
          totalCommitContributions
          totalPullRequestContributions
          totalIssueContributions
          contributionCalendar {
            totalContributions
          }
        }
      }
    }
    """
    result = query_graphql(query, {"login": USERNAME})
    user_data = result['data']['user']
    
    total_repos = user_data['repositories']['totalCount']
    total_commits = user_data['contributionsCollection']['totalCommitContributions']
    total_contributions = user_data['contributionsCollection']['contributionCalendar']['totalContributions']
    
    return total_repos, total_commits, total_contributions

def get_loc():
    # We keep the LOC logic because GraphQL doesn't calculate lines of code
    headers = {'Authorization': f'token {TOKEN}', 'Accept': 'application/vnd.github.v3+json'}
    repos_url = f'https://api.github.com/user/repos?per_page=100&affiliation=owner'
    repos = requests.get(repos_url, headers=headers).json()
    
    loc = 0
    for repo in repos:
        if repo.get('fork'): continue
        stats_url = f"https://api.github.com/repos/{USERNAME}/{repo['name']}/stats/contributors"
        res = requests.get(stats_url, headers=headers)
        if res.status_code == 200:
            stats = res.json()
            for s in stats:
                if s['author']['login'].lower() == USERNAME.lower():
                    for week in s['weeks']: loc += week['a']
    return loc

def generate_svg(repos, commits, contribs, loc):
    svg = f"""<svg width="400" height="210" xmlns="http://www.w3.org/2000/svg">
      <rect width="100%" height="100%" fill="#0d1117" rx="10"/>
      <rect width="100%" height="100%" fill="none" rx="10" stroke="#30363d" stroke-width="2"/>
      <text x="20" y="40" fill="#58a6ff" font-family="Arial" font-size="20" font-weight="bold">{USERNAME}'s Stats</text>
      <text x="20" y="80" fill="#c9d1d9" font-family="Arial" font-size="16">📦 Total Repositories: {repos}</text>
      <text x="20" y="110" fill="#c9d1d9" font-family="Arial" font-size="16">🔥 Total Commits: {commits:,}</text>
      <text x="20" y="140" fill="#79c0ff" font-family="Arial" font-size="16" font-weight="bold">🌟 Total Contributions: {contribs:,}</text>
      <text x="20" y="180" fill="#c9d1d9" font-family="Arial" font-size="16">💻 Lines of Code: {loc:,}</text>
    </svg>"""
    with open('github_stats.svg', 'w') as f: f.write(svg)

if __name__ == "__main__":
    print("Fetching high-accuracy GraphQL stats...")
    repos, commits, contribs = get_stats()
    loc = get_loc()
    generate_svg(repos, commits, contribs, loc)
    print("Done!")
