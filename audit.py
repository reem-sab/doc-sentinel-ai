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


def build_prompt(diff, docs):
    lines = [
        "You are a Senior Technical Writer reviewing a code change for documentation accuracy.",
        "",
        "## Code Change (Diff)",
        diff,
        "",
        "## Current Documentation",
        docs,
        "",
        "## Your Task",
        "1. Analyze whether this code change makes the documentation outdated or inaccurate.",
        "2. If YES: Respond with a severity label (Critical / Minor), a one-sentence explanation of what drifted, and a corrected Markdown snippet ready to paste in.",
        "3. If NO: Respond only with: Documentation is up to date.",
    ]
    return "\n".join(lines)


def run_audit(diff, docs):
    contents = build_prompt(diff, docs)
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="models/gemini-1.5-flash",,
                contents=contents
            )
            return response.text
        except Exception as e:
            if "429" in str(e) and attempt < 2:
                print("Rate limited, retrying in 30 seconds...")
                time.sleep(30)
            else:
                raise


def post_pr_comment(result):
    pr_number = os.getenv("PR_NUMBER")
    if not pr_number:
        return
    repo = g.get_repo(REPO_NAME)
    pr = repo.get_pull(int(pr_number))
    pr.create_issue_comment("## Doc-Sentinel Audit\n\n" + result)
    print("Comment posted to PR.")


try:
    print("Connecting to repo: " + REPO_NAME)
    current_docs = get_real_docs()
    diff = get_real_diff()
    print("Diff captured. Running audit...")
    result = run_audit(diff, current_docs)
    print("\n--- AI AUDIT RESULT ---")
    print(result)
    post_pr_comment(result)

except Exception as e:
    print("Error: " + str(e))
    raise
