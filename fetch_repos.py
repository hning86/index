# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "python-dotenv",
#     "tqdm",
# ]
# ///

import urllib.request
import json
import base64
import re
import sys
import os
from datetime import datetime
import urllib.error
from dotenv import load_dotenv
from tqdm import tqdm

# Load environment variables from .env file
load_dotenv()

# Retrieve GitHub Token if set in the environment
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

# Global flag to stop making requests if we hit rate limits
rate_limited = False

def get_headers():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    if GITHUB_TOKEN:
        headers['Authorization'] = f'Bearer {GITHUB_TOKEN}'
    return headers

def fetch_all_repos(username):
    repos = []
    page = 1
    while True:
        url = f"https://api.github.com/users/{username}/repos?per_page=100&page={page}"
        req = urllib.request.Request(url, headers=get_headers())
        try:
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
                if not data:
                    break
                repos.extend(data)
                page += 1
        except urllib.error.HTTPError as e:
            print(f"HTTP Error fetching repos page {page}: {e.code} {e.reason}", file=sys.stderr)
            if e.code == 403:
                print("Error: GitHub API rate limit exceeded (HTTP 403).", file=sys.stderr)
                if not GITHUB_TOKEN:
                    print("\n💡 TIP: Set GITHUB_TOKEN in your .env file to increase your rate limit from 60 to 5000 requests/hour.", file=sys.stderr)
            break
        except Exception as e:
            print(f"Error fetching page {page}: {e}", file=sys.stderr)
            break
    return repos

def extract_summary_from_markdown(md_content):
    # Remove HTML comments
    md_content = re.sub(r'<!--.*?-->', '', md_content, flags=re.DOTALL)
    # Strip markdown links [text](url) -> text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', md_content)
    # Strip images ![alt](url) -> empty
    text = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', text)
    # Strip inline code `code` -> code
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # Strip bold/italic **text** or *text* -> text
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    # Strip HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Split into lines and look for the first descriptive paragraph
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        # Skip headers, empty lines, blockquotes, list markers, etc.
        if not line:
            continue
        if line.startswith('#') or line.startswith('>') or line.startswith('-') or line.startswith('*') or line.startswith('+') or line.startswith('['):
            continue
        # Skip lines that look like badges or short status indicators
        if len(line) < 15:
            continue
        
        # Take the first substantial line/paragraph
        # Cut at sentence boundary if too long
        sentences = re.split(r'(?<=[.!?])\s+', line)
        summary = sentences[0]
        if len(summary) < 50 and len(sentences) > 1:
            summary += " " + sentences[1]
        
        if len(summary) > 160:
            summary = summary[:157] + "..."
        return summary
    return None

def fetch_readme_summary(username, repo_name):
    global rate_limited
    if rate_limited:
        return None
        
    url = f"https://api.github.com/repos/{username}/{repo_name}/readme"
    req = urllib.request.Request(url, headers=get_headers())
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            content_b64 = data.get("content", "")
            if content_b64:
                md_content = base64.b64decode(content_b64).decode('utf-8', errors='ignore')
                return extract_summary_from_markdown(md_content)
    except urllib.error.HTTPError as e:
        if e.code == 403:
            rate_limited = True
            print("\nWarning: GitHub API rate limit reached. Skipping remaining README fetches.", file=sys.stderr)
    except Exception:
        pass
    return None

def format_date(date_str):
    if not date_str:
        return "N/A"
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return date_str

def categorize_repo(repo):
    name = repo.get("name", "").lower()
    desc = (repo.get("description") or "").lower()
    
    # Check for Agentic / GenAI
    ai_keywords = ['agent', 'gemini', 'adk', 'gpt', 'conversational', 'chatbot', 'llm', 'whoami', 'a2a']
    if any(kw in name or kw in desc for kw in ai_keywords):
        return "Agentic AI & Large Language Models"
        
    # Check for ML/DL
    ml_keywords = ['ml', 'machinelearning', 'deeplearning', 'iris', 'keras', 'tensorflow', 'xgboost', 'lightgbm', 'forecasting', 'predictive', 'parameter', 'spark']
    if any(kw in name or kw in desc for kw in ml_keywords):
        return "Machine Learning & Data Science"
        
    # Check for Cloud/Infrastructure
    cloud_keywords = ['gcp', 'azure', 'cloud', 'docker', 'bicep', 'build', 'dockerfile', 'aws']
    if any(kw in name or kw in desc for kw in cloud_keywords):
        return "Cloud & Infrastructure Tools"
        
    return "Utilities & General Projects"

def main():
    username = "hning86"
    repos = fetch_all_repos(username)
    
    if not repos:
        print("Error: No repositories could be fetched. Exiting.", file=sys.stderr)
        sys.exit(1)
        
    # Sort repos by pushed_at descending (most recently active first)
    repos.sort(key=lambda r: r.get("pushed_at") or "", reverse=True)
    
    # Filter repos that need README enrichment (active since 2024 and no description)
    repos_to_enrich = [
        repo for repo in repos 
        if not repo.get("description") and (repo.get("pushed_at") or "") >= "2024-01-01"
    ]
    
    # Enrich empty descriptions for recent repos with a beautiful tqdm progress bar
    if repos_to_enrich:
        print(f"Enriching descriptions from READMEs for {len(repos_to_enrich)} repositories...", file=sys.stderr)
        for repo in tqdm(repos_to_enrich, desc="Fetching READMEs", unit="repo", file=sys.stderr):
            if rate_limited:
                break
            name = repo.get("name")
            readme_desc = fetch_readme_summary(username, name)
            if readme_desc:
                repo["description"] = f"📖 {readme_desc}"
    else:
        print("No repository descriptions needed enrichment.", file=sys.stderr)
    
    # Categorize repositories
    categorized = {
        "Agentic AI & Large Language Models": [],
        "Machine Learning & Data Science": [],
        "Cloud & Infrastructure Tools": [],
        "Utilities & General Projects": []
    }
    
    for repo in repos:
        category = categorize_repo(repo)
        categorized[category].append(repo)
        
    print(f"# 🗂️ GitHub Repository Index | [@{username}](https://github.com/{username})")
    print("\nWelcome! This is an automatically updated index of my public GitHub repositories, categorized by domain and sorted by recent activity. It serves as a portfolio of my work spanning Agentic AI, Machine Learning, Cloud Infrastructure, and Software Engineering.")
    
    print("\n## 🎯 Focus Areas")
    print("- **🤖 Agentic AI & GenAI**: Implementations of advanced AI agents using Google ADK, LangGraph, and Gemini models.")
    print("- **📊 Machine Learning & Data Science**: Classic ML models, Deep Learning tutorials, and distributed computing frameworks.")
    print("- **☁️ Cloud & Infrastructure**: Deployable cloud architectures, CI/CD templates, and containerized tools.")
    
    # Add a section for Categorized Repositories
    print("\n## 📁 Categorized Portfolio")
    
    for category, cat_repos in categorized.items():
        if not cat_repos:
            continue
        emoji = "🤖" if "Agentic" in category else "📊" if "Machine" in category else "☁️" if "Cloud" in category else "⚙️"
        print(f"\n### {emoji} {category}")
        print(f"*{len(cat_repos)} repositories in this category.*\n")
        
        print("| Repository | Description | Language | Last Pushed | Stars |")
        print("|--- |--- |--- |--- |--- |")
        for repo in cat_repos[:15]: # Show top 15 in each category
            name = repo.get("name")
            html_url = repo.get("html_url")
            desc = repo.get("description") or "*No description provided*"
            desc = desc.replace("\n", " ").replace("\r", "")
            if len(desc) > 120:
                desc = desc[:117] + "..."
            lang = repo.get("language") or "N/A"
            pushed_at = format_date(repo.get("pushed_at"))
            stars = repo.get("stargazers_count", 0)
            
            repo_link = f"[{name}]({html_url})"
            stars_str = f"⭐ {stars}" if stars > 0 else "—"
            print(f"| {repo_link} | {desc} | `{lang}` | {pushed_at} | {stars_str} |")
        
        if len(cat_repos) > 15:
            print(f"| ... and {len(cat_repos) - 15} more older repositories. | | | | |")
            
    # Master Table (All Repositories)
    print("\n## 🕒 Complete Activity Feed")
    print("A complete, chronological list of all public repositories sorted by the most recent push event.\n")
    print("| Repository | Category | Language | Last Pushed | Stars | Forks |")
    print("|--- |--- |--- |--- |--- |--- |")
    
    for repo in repos:
        name = repo.get("name")
        html_url = repo.get("html_url")
        lang = repo.get("language") or "N/A"
        category = categorize_repo(repo)
        # Shorten category name for table
        cat_short = category.replace(" & Large Language Models", "").replace(" & Data Science", "")
        pushed_at = format_date(repo.get("pushed_at"))
        stars = repo.get("stargazers_count", 0)
        forks = repo.get("forks_count", 0)
        
        repo_link = f"[{name}]({html_url})"
        stars_str = f"⭐ {stars}" if stars > 0 else "—"
        forks_str = f"🍴 {forks}" if forks > 0 else "—"
        print(f"| {repo_link} | *{cat_short}* | `{lang}` | {pushed_at} | {stars_str} | {forks_str} |")
        
    print("\n## 🔄 How to Update This Index")
    print("You can easily regenerate and update this `README.md` index file at any time using **uv**.\n")
    print("```bash")
    print("uv run fetch_repos.py > README.md")
    print("```")
    print("\n### 🔑 Environment Variables")
    print("The script loads environment variables from a `.env` file in the root directory. To run this script securely and bypass GitHub rate limits, create a `.env` file containing your Personal Access Token:")
    print("```env")
    print("GITHUB_TOKEN=your_personal_access_token")
    print("```")
    print("\n---\n*This index was automatically generated. Feel free to explore the repositories directly on [GitHub](https://github.com/hning86).*")

if __name__ == "__main__":
    main()
