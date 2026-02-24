import os
import sys
from github import Github, Auth
from google import genai
from dotenv import load_dotenv

# 1. Setup & Authentication
load_dotenv()
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
REPO_NAME = os.getenv("REPO_NAME")
PR_NUMBER = os.getenv("PR_NUMBER")

# Initialize Clients
auth = Auth.Token(GITHUB_TOKEN)
g = Github(auth=auth)
client = genai.Client(api_key=GOOGLE_API_KEY)

def get_pr_diff():
    """Fetches the diff of the current Pull Request."""
    repo = g.get_repo(REPO_NAME)
    pr = repo.get_pull(int(PR_NUMBER))
    comparison = repo.compare(pr.base.sha, pr.head.sha)
    files = comparison.files
    
    full_diff = ""
    affected_filenames = []
    
    for file in files:
        if file.patch: # Only include files with actual changes
            full_diff += f"File: {file.filename}\n{file.patch}\n\n"
            affected_filenames.append(file.filename)
        
    return full_diff, affected_filenames

def get_existing_docs():
    """Fetches the main documentation file to compare against."""
    repo = g.get_repo(REPO_NAME)
    # Confirmed: getting-started.md exists in the repo
    file_content = repo.get_contents("getting-started.md", ref="main")
    return file_content.decoded_content.decode()

def run_ai_audit(diff, docs):
    """Sends the diff and docs to Gemini for analysis."""
    prompt = f"""
    You are a Senior Technical Writer. 
    Review the code changes against the docs. 
    Start with 'YES' if updates are needed, or 'NO' if it's fine.
    
    DIFF: {diff}
    DOCS: {docs}
    """
    
    response = client.models.generate_content(
        model="gemini-2.0-flash-exp",
        contents=prompt
    )
    return response.text

def post_output_to_github(result, files):
    """Sends variables back to the GitHub Actions YAML."""
    # Syntax fixed: Added the mandatory 'else' clause
    label = "Docs: Action Required" if result.strip().startswith("YES") else "Docs: Passed"
    files_list = ", ".join(files) if files else "None"
    
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"audit_label={label}\n")
            f.write(f"affected_files={files_list}\n")

def post_pr_comment(result):
    """Posts the AI audit as a comment on the PR."""
    repo = g.get_repo(REPO_NAME)
    pr = repo.get_pull(int(PR_NUMBER))
    comment_body = f"## 🛡️ Doc-Sentinel AI Audit\n\n{result}"
    pr.create_issue_comment(comment_body)

if __name__ == "__main__":
    if not PR_NUMBER:
        print("No PR_NUMBER found. Skipping.")
        sys.exit(0)

    try:
        diff_text, affected_files = get_pr_diff()
        current_docs = get_existing_docs()
        
        audit_result = run_ai_audit(diff_text, current_docs)
        
        post_output_to_github(audit_result, affected_files)
        post_pr_comment(audit_result)
        
        print("Audit complete!")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
