import os
import subprocess
from github import Github, Auth
from google import genai
from dotenv import load_dotenv

load_dotenv()

auth = Auth.Token(os.getenv("GITHUB_TOKEN"))
g = Github(auth=auth)
REPO_NAME = os.getenv("REPO_NAME", "reem-sab/doc-sentinel-ai")

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))


def get_real_docs(filename="getting-started.md"):
    repo = g.get_repo(REPO_NAME)
    file_content = repo.get_contents(filename)
    return file_content.decoded_content.decode()


def get_real_diff():
    """Pull the actual git diff from the environment (set by GitHub Actions)
    or fall back to comparing HEAD~1 locally for development."""
    diff = os.getenv("GIT_DIFF")
    if diff:
        return diff
    result = subprocess.run(
        ["git", "diff", "HEAD~1", "HEAD", "--", "*.py", "*.md"],
        capture_output=True, text=True
    )
    return result.stdout or "No diff available."


def run_audit(diff, docs):
    prompt = f"""
You are a Senior Technical Writer reviewing a code change for documentation accuracy.

## Code Change (Diff)
