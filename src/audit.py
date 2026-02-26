import os
import sys
import re
import json
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


def get_pr_data(repo, pr_number):
    """Gets diff and doc content for a pull request trigger."""
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

    return diff_text, doc_content, affected_files, pr


def parse_doc_detective_issue(issue_body, repo_name):
    """
    Parses a Doc Detective failure issue body.
    Extracts the JSON report and converts runner paths to repo-relative paths.
    """
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', issue_body, re.DOTALL)
    if not match:
        raise ValueError("Could not find JSON report in issue body.")

    report = json.loads(match.group(1))

    short_repo_name = repo_name.split("/")[-1]
    runner_prefix = "/home/runner/work/" + short_repo_name + "/" + short_repo_name + "/"

    failed_files = []
    failed_steps = []

    for spec in report.get("specs", []):
        raw_path = spec.get("file", "")
        repo_relative_path = raw_path.replace(runner_prefix, "")
        if spec.get("result") == "FAIL":
            failed_files.append(repo_relative_path)

        for test in spec.get("tests", []):
            for context in test.get("contexts", []):
                for step in context.get("steps", []):
                    if step.get("result") == "FAIL":
                        failed_steps.append({
                            "file": repo_relative_path,
                            "action": step.get("action"),
                            "description": step.get("resultDescription")
                        })

    return failed_files, failed_steps


def get_issue_data(repo, issue_number):
    """Gets doc content and failure details for a Doc Detective issue trigger."""
    issue = repo.get_issue(int(issue_number))
    repo_name = repo.full_name

    failed_files, failed_steps = parse_doc_detective_issue(issue.body, repo_name)

    if not failed_files:
        raise ValueError("No failed files found in Doc Detective report.")

    doc_path = failed_files[0]

    try:
        doc_file = repo.get_contents(doc_path, ref="main")
        doc_content = doc_file.decoded_content.decode()
    except Exception:
        doc_content = "Could not retrieve file: " + doc_path

    failure_summary = "Doc Detective detected the following failures:\n"
    for step in failed_steps:
        failure_summary += "- " + step["description"] + " (action: " + step["action"] + ")\n"

    return doc_content, doc_path, failure_summary, issue


def run_pr_audit(diff, docs, score):
    """Runs a drift + style audit for a pull request trigger."""
    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

    prompt = (
        "You are a Senior Technical Writer reviewing a pull request. "
        "Perform a two-part audit and respond in this exact format:\n\n"
        "**DRIFT AUDIT**\n"
        "Start with YES or NO in bold. One sentence explaining what drifted and why it matters. "
        "If YES, provide a corrected Markdown snippet under a heading called Suggested Fix.\n\n"
        "**STYLE AUDIT**\n"
        "Two to three bullet points maximum. Each bullet is one specific, actionable suggestion. "
        "No preamble. No summary. No encouragement. Just the fixes.\n\n"
        "The document currently has an AI-Readability score of " + str(score) + "%.\n\n"
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


def run_issue_audit(doc_content, failure_summary, score):
    """Runs a targeted audit based on a Doc Detective failure report."""
    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

    prompt = (
        "You are a Senior Technical Writer. Doc Detective ran automated tests on a documentation file and found failures.\n\n"
        "FAILURE SUMMARY:\n" + failure_summary + "\n\n"
        "Respond in this exact format:\n\n"
        "**FAILURE AUDIT**\n"
        "One sentence identifying what in the documentation is inaccurate or missing that caused these failures.\n\n"
        "**SUGGESTED FIX**\n"
        "The corrected Markdown snippet only. No explanation before or after it.\n\n"
        "**STYLE AUDIT**\n"
        "Two to three bullet points maximum. Each bullet is one specific, actionable suggestion. "
        "No preamble. No summary. No encouragement. Just the fixes.\n\n"
        "The document currently has an AI-Readability score of " + str(score) + "%.\n\n"
        "EXISTING DOCS:\n" + doc_content
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
    github_token = os.getenv("GITHUB_TOKEN")
    repo_name = os.getenv("REPO_NAME")
    pr_number = os.getenv("PR_NUMBER")
    issue_number = os.getenv("ISSUE_NUMBER")

    auth = Auth.Token(github_token)
    g = Github(auth=auth)
    repo = g.get_repo(repo_name)

    # --- PULL REQUEST TRIGGER ---
    if pr_number:
        print("PR trigger detected. Running drift audit...")
        try:
            diff, docs, files, pr = get_pr_data(repo, pr_number)

            intel = DocSentinelIntelligence(docs)
            readability_score = intel.calculate_score()

            audit_result = run_pr_audit(diff, docs, readability_score)

            label = "Docs: Action Required" if audit_result.strip().startswith("YES") or "**YES**" in audit_result else "Docs: Passed"
            if "GITHUB_OUTPUT" in os.environ:
                with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                    f.write("audit_label=" + label + "\n")
                    f.write("affected_files=" + ", ".join(files) + "\n")
                    f.write("readability_score=" + str(readability_score) + "%\n")

            comment_header = "## 🛡️ Doc-Sentinel Audit Result\n**AI-Readability Score: " + str(readability_score) + "%**\n\n"
            pr.create_issue_comment(comment_header + audit_result)

            print("PR audit complete.")

        except Exception as e:
            print("CRITICAL ERROR (PR): " + str(e))
            sys.exit(1)

    # --- DOC DETECTIVE ISSUE TRIGGER ---
    elif issue_number:
        print("Doc Detective issue trigger detected. Running targeted audit...")
        try:
            doc_content, doc_path, failure_summary, issue = get_issue_data(repo, issue_number)

            intel = DocSentinelIntelligence(doc_content)
            readability_score = intel.calculate_score()

            audit_result = run_issue_audit(doc_content, failure_summary, readability_score)

            comment = (
                "## 🛡️ Doc-Sentinel Audit Result\n"
                "**Triggered by:** Doc Detective test failure\n"
                "**File audited:** `" + doc_path + "`\n"
                "**AI-Readability Score:** " + str(readability_score) + "%\n\n"
                + audit_result
            )
            issue.create_comment(comment)

            print("Issue audit complete.")

        except Exception as e:
            print("CRITICAL ERROR (Issue): " + str(e))
            sys.exit(1)

    else:
        print("No PR or issue detected. Exiting.")
        sys.exit(0)
