import os
import subprocess
import time
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
    diff = os.getenv("GIT_DIFF")
    if diff:
        return diff
    cmd = ["git", "diff", "HEAD~1", "HEAD", "--", "*.py", "*.md"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout or "No diff available."


def run_audit(diff, docs):
    contents = "You are a Senior Technical Writer reviewing a code change for documentation accuracy.\n\n"
    contents += "## Code Change (Diff)\n"
    contents += diff + "\n\n"
    contents += "## Curr
