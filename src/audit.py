import os
import sys
import re
from github import Github, Auth
from google import genai
from dotenv import load_dotenv

load_dotenv()

class DocSentinelIntelligence:
    """The new 'Intelligence' part - handles the style scoring logic."""
    def __init__(self, content):
        self.content = content

    def calculate_score(self):
        """Calculates a basic AI-readability score using heuristics."""
        score = 100
        # Check for vague pronouns at start of lines (bad for AI context)
        pronouns = len(re.findall(r'(?m)^(\s*)(It|This|They|Those)\s', self.content))
        score -= min(pronouns * 10, 40)
        # Check for basic Markdown structure (subheaders)
        if not re.search(r'^## ', self.content, re.M):
            score -= 20
        return max(score, 0)

# --- THE DRIFT DETECTION & INTEGRATION CORE ---

def get_pr_data():
    """THE DRIFT PART: Captures code changes vs existing docs."""
    github_token = os.getenv("GITHUB_TOKEN")
    repo_name = os.getenv("REPO_NAME")
    pr_number = os.getenv("PR_NUMBER")
    
    auth = Auth.Token(github_token)
    g = Github(auth=auth)
    repo = g.get_repo(repo_name)
    pr = repo.get_pull(int(pr_number))
    
    # 1. Get the DIFF (The actual code changes)
    comparison = repo.compare(pr.base.sha, pr.head.sha)
    diff_text = ""
    affected_files = []
    for file in comparison.files:
        if file.patch:
            diff_text += f"File: {file.filename}\n{file.patch}\n\n"
            affected_files.append(file.filename)
            
    # 2. Get the EXISTING DOCS
    doc_file = repo.get_contents("getting-started.md", ref="main")
    doc_content = doc_file.decoded_content.decode()
    
    return diff_text, doc_content, affected_files, pr, repo

def run_unified_audit(diff, docs, score):
    """The Brain: Audits for BOTH Drift and Style."""
    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    
    prompt = f"""
    Act as a Senior Technical Writer. Perform a two-part audit:
    
    1. DRIFT AUDIT: Compare the CODE DIFF below to the EXISTING DOCS. 
       If the code changes are not reflected in the docs, start with 'YES'. Otherwise, start with 'NO'.
    
    2. STYLE AUDIT: The document currently has an AI-Readability score of {score}%. 
       Suggest improvements to make it more 'Agent-Friendly'.
    
    CODE DIFF:
    {diff}
    
    EXISTING DOCS:
    {docs}
    """
    
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt
    )
    return response.text

if __name__ == "__main__":
    if not os.getenv("PR_NUMBER"):
        print("No PR detected. Exiting.")
        sys.exit(0)

    try:
        # Step 1: Get the Drift Data (The part we almost lost!)
        diff, docs, files, pr, repo = get_pr_data()
        
        # Step 2: Calculate the Intelligence Score
        intel = DocSentinelIntelligence(docs)
        readability_score = intel.calculate_score()
        
        # Step 3: Run the AI Audit for Drift + Style
        audit_result = run_unified_audit(diff, docs, readability_score)
        
        # Step 4: Handle GitHub Outputs for Labels/Summary
        label = "Docs: Action Required" if audit_result.strip().startswith("YES") else "Docs: Passed"
        if "GITHUB_OUTPUT" in os.environ:
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write(f"audit_label={label}\n")
                f.write(f"affected_files={', '.join(files)}\n")
                f.write(f"readability_score={readability_score}%\n")
        
        # Step 5: Post the unified comment
        comment_header = f"## 🛡️ Doc-Sentinel Audit Result\n**AI-Readability Score: {readability_score}%**\n\n"
        pr.create_issue_comment(comment_header + audit_result)
        
        print("Audit successful.")
        
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        sys.exit(1)
