import os
import sys
import re
import time
from github import Github, Auth
from google import genai
from dotenv import load_dotenv

load_dotenv()


class DocSentinelIntelligence:
    """Handles the AI-readability scoring logic."""
    def __init__(self, content):
        self.content = content

    def calculate_score(self):
        score = 100
        pronouns = len(re.findall(r'(?m)^(\s*)(It|This|They|Those)\s', self.content))
        score -= min(pronouns * 10, 40)
        if not re.search(r'^## ', self.content, re.M):
            score -= 20
        return max(score, 0)


def get_pr_data():
    github_token = os.getenv("GITHUB_TOKEN")
    repo_name = os.getenv("REPO_NAME")
    pr_number = os.getenv("PR_NUMBER")

    auth = Auth.Token(github_token)
    g = Github(auth=auth)
    repo = g.get_repo(repo_name)
    pr = repo.get_pull(int(pr_number))

    comparison = repo.compare(pr.base.sha, pr.head.sha)
    diff_text = ""
    affected_files = []
    for file in comparison.files:
        if file.patch:
            diff_text += "File: " + file.filename + "\n" + file.patch + "\n\n"
            affected_files.append(file.filename)

    doc_file = repo.get_contents("getting-started.md", ref="main")
    doc_content = doc_file.decoded_content.decode()

    return diff_text, doc_content, affected_files, pr, repo


def run_unified_audit(diff, docs, score):
    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

    prompt = (
        "Act as a Senior Technical Writer. Perform a two-part audit:\n\n"
        "1. DRIFT AUDIT: Compare the CODE DIFF below to the EXISTING DOCS.\n"
        "   If the code changes are not reflected in the docs, start with YES. Otherwise, start with NO.\n\n"
        "2. STYLE AUDIT: The document currently has an AI-Readability score of " + str(score) + "%.\n"
        "   Suggest improvements to make it more Agent-Friendly.\n\n"
        "CODE DIFF:\n" + diff + "\n\n"
        "EXISTING DOCS:\n" + docs
    )

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt
            )
            return response.text
        except Exception as e:
            if "429" in str(e) and attempt < 2:
                print("Rate limited, retrying in 30 seconds...")
                time.sleep(30)
            else:
                raise


if __name__ == "__main__":
    if not os.getenv("PR_NUMBER"):
        print("No PR detected. Exiting.")
        sys.exit(0)

    try:
        diff, docs, files, pr, repo = get_pr_data()

        intel = DocSentinelIntelligence(docs)
        readability_score = intel.calculate_score()

        audit_result = run_unified_audit(diff, docs, readability_score)

        label = "Docs: Action Required" if audit_result.strip().startswith("YES") else "Docs: Passed"
        if "GITHUB_OUTPUT" in os.environ:
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write("audit_label=" + label + "\n")
                f.write("affected_files=" + ", ".join(files) + "\n")
                f.write("readability_score=" + str(readability_score) + "%\n")

        comment_header = "## Doc-Sentinel Audit Result\n**AI-Readability Score: " + str(readability_score) + "%**\n\n"
        pr.create_issue_comment(comment_header + audit_result)

        print("Audit successful.")

    except Exception as e:
        print("CRITICAL ERROR: " + str(e))
        sys.exit(1)
