#!/usr/bin/env python3
"""
Doc-Sentinel Historical Audit
------------------------------
Scans your entire repository for documentation drift.
Run this once to get a full picture of your existing documentation health.

Usage:
    python historical_audit.py --repo OWNER/REPO [--all] [--output report.md]

Flags:
    --repo      Required. Your GitHub repo in OWNER/REPO format.
    --all       Audit every .md file. Default: only files with matching code files.
    --output    Path to save the Markdown report. Default: doc-sentinel-report.md
    --token     GitHub token. Defaults to GITHUB_TOKEN env var.
    --key       Google API key. Defaults to GOOGLE_API_KEY env var.
"""

import os
import re
import sys
import time
import argparse
from datetime import datetime
from github import Github, Auth
from google import genai


# --- ARGUMENT PARSING ---

def parse_args():
    parser = argparse.ArgumentParser(description="Doc-Sentinel Historical Audit")
    parser.add_argument("--repo", required=True, help="GitHub repo in OWNER/REPO format")
    parser.add_argument("--all", action="store_true", dest="audit_all",
                        help="Audit every .md file. Default: only files with matching code files.")
    parser.add_argument("--output", default="doc-sentinel-report.md",
                        help="Path to save the Markdown report (default: doc-sentinel-report.md)")
    parser.add_argument("--token", default=None, help="GitHub token (defaults to GITHUB_TOKEN env var)")
    parser.add_argument("--key", default=None, help="Google API key (defaults to GOOGLE_API_KEY env var)")
    return parser.parse_args()


# --- REPO SCANNING ---

def get_all_files(repo):
    """Recursively fetch all files in the repo and return two lists: md files and code files."""
    md_files = []
    code_extensions = {'.py', '.js', '.ts', '.go', '.java', '.rb', '.rs', '.cpp', '.c', '.cs', '.php'}
    code_files = []

    print("Scanning repository...")
    try:
        stack = list(repo.get_contents("", ref="main"))
        while stack:
            item = stack.pop()
            if item.type == "dir":
                stack.extend(repo.get_contents(item.path, ref="main"))
            elif item.path.endswith(".md"):
                md_files.append(item.path)
            elif any(item.path.endswith(ext) for ext in code_extensions):
                code_files.append(item.path)
    except Exception as e:
        print("Error scanning repo: " + str(e))
        sys.exit(1)

    print("Found " + str(len(md_files)) + " Markdown files and " + str(len(code_files)) + " code files.")
    return md_files, code_files


def find_matching_code(doc_path, code_files):
    """Find code files that match a given doc file by name."""
    doc_base = os.path.basename(doc_path)
    doc_base = os.path.splitext(doc_base)[0].lower().replace("_", "-")

    matches = []
    for code_path in code_files:
        code_base = os.path.basename(code_path)
        code_base = os.path.splitext(code_base)[0].lower().replace("_", "-")
        if doc_base in code_base or code_base in doc_base:
            matches.append(code_path)
    return matches


def get_file_content(repo, path):
    """Fetch the decoded content of a file from the repo."""
    try:
        f = repo.get_contents(path, ref="main")
        return f.decoded_content.decode()
    except Exception:
        return None


# --- SCORING ---

def calculate_readability_score(content):
    """Calculate AI-readability score using heuristics from the style guide."""
    score = 100
    pronouns = len(re.findall(r'(?m)^(\s*)(It|This|They|Those)\s', content))
    score -= min(pronouns * 10, 40)
    if not re.search(r'^## ', content, re.M):
        score -= 20
    return max(score, 0)


# --- GEMINI AUDIT ---

def run_historical_audit(doc_content, code_content, doc_path, code_path, score, client):
    """Ask Gemini whether the doc is still accurate given the current code."""
    prompt = (
        "You are a Senior Technical Writer performing a documentation health check.\n\n"
        "Your job is to compare the CURRENT DOCUMENTATION against the CURRENT CODE and determine "
        "whether the documentation is still accurate.\n\n"
        "Respond in this exact format:\n\n"
        "**ACCURACY**\n"
        "Start with ACCURATE, OUTDATED, or PARTIAL in bold. One sentence explaining your verdict.\n\n"
        "**ISSUES FOUND**\n"
        "Bullet list of specific inaccuracies, outdated references, or missing information. "
        "If none, write 'None detected.'\n\n"
        "**SUGGESTED FIXES**\n"
        "For each issue, provide the corrected Markdown snippet. If none, write 'No fixes needed.'\n\n"
        "**STYLE NOTES**\n"
        "One or two bullets on AI-readability improvements. The document scores " + str(score) + "%.\n\n"
        "CURRENT DOCUMENTATION (" + doc_path + "):\n" + doc_content + "\n\n"
        "CURRENT CODE (" + code_path + "):\n" + code_content
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
                print("  Rate limited, retrying in 30 seconds...")
                time.sleep(30)
            else:
                return "Error running audit: " + str(e)


def run_doc_only_audit(doc_content, doc_path, score, client):
    """Audit a doc file with no matching code — check for general accuracy and style."""
    prompt = (
        "You are a Senior Technical Writer performing a documentation health check.\n\n"
        "No matching code file was found for this document. Review it for general accuracy, "
        "clarity, and AI-readability.\n\n"
        "Respond in this exact format:\n\n"
        "**ACCURACY**\n"
        "Start with ACCURATE, OUTDATED, or PARTIAL in bold. One sentence explaining your verdict.\n\n"
        "**ISSUES FOUND**\n"
        "Bullet list of vague claims, missing context, or structural problems. "
        "If none, write 'None detected.'\n\n"
        "**STYLE NOTES**\n"
        "One or two bullets on AI-readability improvements. The document scores " + str(score) + "%.\n\n"
        "CURRENT DOCUMENTATION (" + doc_path + "):\n" + doc_content
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
                print("  Rate limited, retrying in 30 seconds...")
                time.sleep(30)
            else:
                return "Error running audit: " + str(e)


# --- REPORT GENERATION ---

def build_report(results, repo_name, audit_all, timestamp):
    """Build the full Markdown report from audit results."""
    total = len(results)
    accurate = sum(1 for r in results if r["status"] == "ACCURATE")
    outdated = sum(1 for r in results if r["status"] == "OUTDATED")
    partial = sum(1 for r in results if r["status"] == "PARTIAL")
    avg_score = int(sum(r["score"] for r in results) / total) if total > 0 else 0

    report = "# 🛡️ Doc-Sentinel Historical Audit Report\n\n"
    report += "**Repository:** " + repo_name + "\n"
    report += "**Date:** " + timestamp + "\n"
    report += "**Mode:** " + ("All .md files" if audit_all else "Files with matching code only") + "\n\n"
    report += "---\n\n"

    report += "## 📊 Summary\n\n"
    report += "| Metric | Result |\n"
    report += "| :--- | :--- |\n"
    report += "| **Files audited** | " + str(total) + " |\n"
    report += "| **Accurate** | " + str(accurate) + " |\n"
    report += "| **Outdated** | " + str(outdated) + " |\n"
    report += "| **Partial** | " + str(partial) + " |\n"
    report += "| **Avg AI-Readability Score** | " + str(avg_score) + "% |\n\n"
    report += "---\n\n"

    # Outdated files first
    outdated_results = [r for r in results if r["status"] in ("OUTDATED", "PARTIAL")]
    if outdated_results:
        report += "## ⚠️ Files Requiring Attention\n\n"
        for r in outdated_results:
            report += "### `" + r["doc_path"] + "`\n"
            report += "**AI-Readability Score:** " + str(r["score"]) + "%"
            if r["code_path"]:
                report += " | **Matched code file:** `" + r["code_path"] + "`"
            report += "\n\n"
            report += r["audit_result"] + "\n\n---\n\n"

    # Accurate files
    accurate_results = [r for r in results if r["status"] == "ACCURATE"]
    if accurate_results:
        report += "## ✅ Files in Good Shape\n\n"
        for r in accurate_results:
            report += "- `" + r["doc_path"] + "` — AI-Readability Score: " + str(r["score"]) + "%\n"
        report += "\n"

    report += "---\n\n"
    report += "*Generated by [Doc-Sentinel AI](https://reem-sab.github.io/doc-sentinel-ai/)*\n"
    return report


# --- MAIN ---

def main():
    args = parse_args()

    github_token = args.token or os.getenv("GITHUB_TOKEN")
    google_key = args.key or os.getenv("GOOGLE_API_KEY")

    if not github_token:
        print("Error: GitHub token required. Set GITHUB_TOKEN or use --token.")
        sys.exit(1)
    if not google_key:
        print("Error: Google API key required. Set GOOGLE_API_KEY or use --key.")
        sys.exit(1)

    auth = Auth.Token(github_token)
    g = Github(auth=auth)
    repo = g.get_repo(args.repo)
    client = genai.Client(api_key=google_key)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    print("\n🛡️  Doc-Sentinel Historical Audit")
    print("Repository: " + args.repo)
    print("Mode: " + ("All .md files" if args.audit_all else "Files with matching code only"))
    print("Report will be saved to: " + args.output + "\n")

    md_files, code_files = get_all_files(repo)

    results = []

    for doc_path in md_files:
        print("Auditing: " + doc_path)

        doc_content = get_file_content(repo, doc_path)
        if not doc_content:
            print("  Could not retrieve file. Skipping.")
            continue

        score = calculate_readability_score(doc_content)
        matching_code = find_matching_code(doc_path, code_files)

        if matching_code:
            code_path = matching_code[0]
            code_content = get_file_content(repo, code_path)
            if not code_content:
                code_path = None
                audit_result = run_doc_only_audit(doc_content, doc_path, score, client)
            else:
                audit_result = run_historical_audit(doc_content, code_content, doc_path, code_path, score, client)
        elif args.audit_all:
            code_path = None
            audit_result = run_doc_only_audit(doc_content, doc_path, score, client)
        else:
            print("  No matching code file found. Skipping (use --all to include).")
            continue

        # Determine status from audit result
        if "**OUTDATED**" in audit_result or audit_result.strip().startswith("OUTDATED"):
            status = "OUTDATED"
        elif "**PARTIAL**" in audit_result or audit_result.strip().startswith("PARTIAL"):
            status = "PARTIAL"
        else:
            status = "ACCURATE"

        results.append({
            "doc_path": doc_path,
            "code_path": code_path if matching_code else None,
            "score": score,
            "status": status,
            "audit_result": audit_result
        })

        print("  Status: " + status + " | Score: " + str(score) + "%")
        time.sleep(2)  # Be gentle with the API

    if not results:
        print("\nNo files were audited. Try running with --all to include all .md files.")
        sys.exit(0)

    # Build and save report
    report = build_report(results, args.repo, args.audit_all, timestamp)

    with open(args.output, "w") as f:
        f.write(report)
    print("\nReport saved to: " + args.output)

    # Print summary to terminal
    total = len(results)
    outdated = sum(1 for r in results if r["status"] in ("OUTDATED", "PARTIAL"))
    print("\n--- SUMMARY ---")
    print("Files audited: " + str(total))
    print("Requiring attention: " + str(outdated))
    print("Healthy: " + str(total - outdated))
    print("---------------\n")

    if outdated > 0:
        print("⚠️  Documentation drift detected. Review " + args.output + " for details.")
    else:
        print("✅ All audited documentation looks healthy.")


if __name__ == "__main__":
    main()
