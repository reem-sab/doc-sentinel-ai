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
    # We get the 'diff' format specifically to show the changes
    comparison = repo.get_compare(pr.base.sha, pr.head.sha)
    files = comparison.files
    
    full_diff = ""
    affected_filenames = []
    
    for file in files:
        full_diff += f"File: {file.filename}\n{file.patch}\n\n"
        affected_filenames.append(file.filename)
        
    return full_diff, affected_filenames

def get_existing_docs():
    """Fetches the main documentation file to compare against."""
    repo = g.get_repo(REPO_NAME)
    # Update this path to your specific docs file (e.g., 'README.md' or 'docs/index.md')
    file_content = repo.get_contents("getting-started.md", ref="main")
    return file_content.decoded_content.decode()

def run_ai_audit(diff, docs):
    """Sends the diff and docs to Gemini for analysis."""
    prompt = f"""
    You are a Senior Technical Writer and Documentation Auditor.
    
    TASK:
    Review the following code changes (Diff) against the existing documentation.
    Determine if the documentation is now outdated or missing new features.
    
    - If documentation needs updates: Start your response with 'YES'.
    - If documentation is fine: Start your response with 'NO'.
    
    Provide a concise explanation and, if 'YES', provide the suggested Markdown fix.
    
    CODE CHANGE (DIFF):
    {diff}
    
    EXISTING DOCUMENTATION:
    {docs}
    """
    
    response = client.models.generate_content(
        model="gemini-1.5-flash",
        contents=prompt
    )
    return response.text

def post_output_to_github(result, files):
    """Sends variables back to the GitHub Actions YAML."""
    # Fixed the SyntaxError by adding the 'else' clause
    label = "Docs: Action Required" if result.strip().startswith("YES") else "Docs: Passed"
    files_list = ", ".join(files) if files else "None"
    
    # Ensure we write to the GitHub output file correctly
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"audit_label={label}\n")
            f.write(f"affected_files={files_list}\n")
