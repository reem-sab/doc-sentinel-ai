import os
import subprocess
from github import Github, Auth
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

auth = Auth.Token(os.getenv("GITHUB_TOKEN"))
g = Github(auth=auth)
REPO_NAME = os.getenv("REPO_NAME", "reem-sab/doc-sentinel-ai")

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def get_real_docs(filename="getting-started.md"):
    repo = g.get_repo(REPO_NAME)
    file_content = repo.get_contents(filename)
    return file_content.decoded_content.decode()


def get_real_diff():
    diff = os.getenv("GIT_DIFF")
    if diff:
        return diff
    result = subprocess.run(
        ["git", "diff", "HEAD~1", "HEAD", "--", "*.py", "*.md"],
        capture_output=True, text=True
    )
    return result.stdout or "No diff available."


def run_audit(diff, docs):
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": (
                    "You are a Senior Technical Writer reviewing a code change for documentation accuracy.\n\n"
                    "## Code Change (Diff)\n"
                    f"{diff}\n\n"
                    "## Current Documentation\n"
                    f"{docs}\n\n"
                    "## Your Task\n"
                    "1. Analyze whether this code change makes the documentation outdated or inaccurate.\n"
                    "2. If YES: Respond with a severity label (Critical / Minor), a one-sentence explanation "
                    "of what drifted, and a corrected Markdown snippet ready to paste in.\n"
                    "3. If NO: Respond only with: Documentation is up to date."
                )
            }
        ]
    )
    return message.content[0].text


def post_pr_comment(result):
    pr_number = os.getenv("PR_NUMBER")
    if not pr_number:
        return
    repo = g.get_repo(REPO_NAME)
    pr = repo.get_pull(int(pr_number))
    pr.create_issue_comment(f"## Doc-Sentinel Audit\n\n{result}")
    print("Comment posted to PR.")


try:
    print(f"Connecting to repo: {REPO_NAME}")
    current_docs = get_real_docs()
    diff = get_real_diff()

    print(f"Diff captured ({len(diff)} chars). Running audit...")
    result = run_audit(diff, current_docs)

    print("\n--- AI AUDIT RESULT ---")
    print(result)

    post_pr_comment(result)

except Exception as e:
    print(f"Error: {e}")
    raise
