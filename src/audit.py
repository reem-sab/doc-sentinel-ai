import os
import sys
import re
import json
from github import Github, Auth
from dotenv import load_dotenv

# Anonymous, fail-open developer telemetry. Imported defensively so a missing
# or broken telemetry module can never stop an audit from running, whether this
# file is run directly (python src/audit.py) or imported as src.audit.
try:
    from telemetry import track_event, track_crash, flush_telemetry
except Exception:  # pragma: no cover - telemetry is strictly best-effort
    try:
        from src.telemetry import track_event, track_crash, flush_telemetry
    except Exception:
        def track_event(*args, **kwargs):
            pass

        def track_crash(*args, **kwargs):
            pass

        def flush_telemetry(*args, **kwargs):
            pass

# Drift check logic lives in drift_core so the GitHub Action and the MCP
# server share it. Same dual import as telemetry: direct run or src.audit.
try:
    from drift_core import (
        DocSentinelIntelligence, list_repo_md_files, match_docs, format_diff,
        run_single_doc_audit, run_issue_audit, has_drift, is_critical, FALLBACK_DOC,
    )
except ImportError:
    from src.drift_core import (
        DocSentinelIntelligence, list_repo_md_files, match_docs, format_diff,
        run_single_doc_audit, run_issue_audit, has_drift, is_critical, FALLBACK_DOC,
    )

load_dotenv()


def find_matching_docs(repo, changed_files):
    """
    Multi-file support: For each changed code file, find matching .md files
    by comparing base names. Falls back to getting-started.md if no match found.
    """
    try:
        all_md_files = list_repo_md_files(repo)
    except Exception as e:
        print("Could not scan repo for .md files: " + str(e))
        return [FALLBACK_DOC]

    return match_docs(all_md_files, changed_files)


def get_pr_data(repo, pr_number):
    """Gets diff and changed files for a pull request trigger."""
    pr = repo.get_pull(int(pr_number))

    comparison = repo.compare(pr.base.sha, pr.head.sha)
    diff_text, affected_files = format_diff(
        (file.filename, file.patch) for file in comparison.files
    )

    return diff_text, affected_files, pr


def get_doc_content(repo, doc_path):
    """Fetches the content of a doc file from the repo."""
    try:
        doc_file = repo.get_contents(doc_path, ref="main")
        return doc_file.decoded_content.decode()
    except Exception:
        return None


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


if __name__ == "__main__":
    github_token = os.getenv("GITHUB_TOKEN")
    repo_name = os.getenv("REPO_NAME")
    pr_number = os.getenv("PR_NUMBER")
    issue_number = os.getenv("ISSUE_NUMBER")

    # --- TELEMETRY: audit invocation started (trigger resolved) ---
    # Records the trigger type and whether a custom config is present. No repo
    # name, PR/issue numbers, tokens, or other identifying data is captured.
    if pr_number:
        scan_type = "pull_request"
    elif issue_number:
        scan_type = "doc_detective_issue"
    else:
        scan_type = "none"
    track_event("cli_audit_started", {
        "scan_type": scan_type,
        "trigger_source": "github_actions",
        "custom_config_found": os.path.exists("sentinel.yaml"),
    })

    auth = Auth.Token(github_token)
    g = Github(auth=auth)
    repo = g.get_repo(repo_name)

    # --- PULL REQUEST TRIGGER ---
    if pr_number:
        print("PR trigger detected. Running multi-file drift audit...")
        try:
            diff, affected_files, pr = get_pr_data(repo, pr_number)

            doc_files = find_matching_docs(repo, affected_files)
            print("Doc files to audit: " + str(doc_files))

            combined_comment = "## 🛡️ Doc-Sentinel Audit Result\n"
            combined_comment += "**Files audited:** " + ", ".join(["`" + f + "`" for f in doc_files]) + "\n\n"
            combined_comment += "---\n\n"

            any_drift = False
            any_critical = False
            drift_count = 0

            for doc_path in doc_files:
                doc_content = get_doc_content(repo, doc_path)
                if not doc_content:
                    combined_comment += "### `" + doc_path + "`\n"
                    combined_comment += "⚠️ Could not retrieve this file.\n\n---\n\n"
                    continue

                intel = DocSentinelIntelligence(doc_content)
                readability_score = intel.calculate_score()

                audit_result = run_single_doc_audit(diff, doc_content, doc_path, readability_score)

                if has_drift(audit_result):
                    any_drift = True
                    drift_count += 1
                if is_critical(audit_result):
                    any_critical = True

                combined_comment += "### `" + doc_path + "`\n"
                combined_comment += "**AI-Readability Score:** " + str(readability_score) + "%\n\n"
                combined_comment += audit_result + "\n\n---\n\n"

            pr.create_issue_comment(combined_comment)

            if any_critical:
                label = "Docs: Critical Drift"
            elif any_drift:
                label = "Docs: Action Required"
            else:
                label = "Docs: Passed"

            # --- TELEMETRY: documentation drift anomalies caught this run ---
            if drift_count > 0:
                track_event("drift_detected", {
                    "drift_count": drift_count,
                    "highest_severity": "critical" if any_critical else "minor",
                    "files_audited": len(doc_files),
                })

            if "GITHUB_OUTPUT" in os.environ:
                with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                    f.write("audit_label=" + label + "\n")
                    f.write("affected_files=" + ", ".join(affected_files) + "\n")

            print("PR audit complete. Files audited: " + str(len(doc_files)))

        except Exception as e:
            print("CRITICAL ERROR (PR): " + str(e))
            track_crash(e)
            sys.exit(1)
        finally:
            # Drain queued events before the fast-terminating process exits.
            flush_telemetry()

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

            # --- TELEMETRY: a Doc Detective failure is a caught drift anomaly ---
            track_event("drift_detected", {
                "drift_count": 1,
                "highest_severity": "critical" if is_critical(audit_result) else "minor",
                "files_audited": 1,
            })

            print("Issue audit complete.")

        except Exception as e:
            print("CRITICAL ERROR (Issue): " + str(e))
            track_crash(e)
            sys.exit(1)
        finally:
            # Drain queued events before the fast-terminating process exits.
            flush_telemetry()

    else:
        print("No PR or issue detected. Exiting.")
        flush_telemetry()
        sys.exit(0)
