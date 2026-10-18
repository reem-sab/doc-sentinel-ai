"""
Doc-Sentinel Drift Core
-----------------------
The drift check as plain functions, shared by every entry point:

    * src/audit.py                      GitHub Action (PR comments, labels)
    * mcp_servers/drift_check_server.py the MCP tool the remediation agent calls

Nothing here talks to the GitHub API. Callers hand in file lists, diffs, and
doc text, either fetched from GitHub (audit.py) or read from a local checkout
(the local helpers at the bottom of this file).

Environment variables:
    DOC_SENTINEL_CHECKER_PROVIDER  Model provider for the drift check (default: gemini).
    DOC_SENTINEL_CHECKER_MODEL     Model name for the drift check (default: gemini-2.0-flash).
    DOC_SENTINEL_FAIL_ON_MINOR     Set to "true" to treat MINOR drift as a failure.
    GOOGLE_API_KEY                 Required by the gemini provider.
"""

import os
import re
import sys
import time
import hashlib
import subprocess
from dataclasses import dataclass, field, asdict

from google import genai


DEFAULT_CHECKER_PROVIDER = "gemini"
DEFAULT_CHECKER_MODEL = "gemini-2.0-flash"

# Doc audited when no doc file name matches a changed code file.
FALLBACK_DOC = "getting-started.md"


# --- CHECKER CONFIGURATION ----------------------------------------------------

def checker_settings():
    """
    Return the provider and model the drift check runs on.

    Read on every call, not at import, so a .env file loaded by the caller
    still applies. `or` (not a get default) so an empty env var, such as an
    unset CI secret, falls back to the default instead of a blank value.
    """
    return {
        "provider": os.environ.get("DOC_SENTINEL_CHECKER_PROVIDER") or DEFAULT_CHECKER_PROVIDER,
        "model": os.environ.get("DOC_SENTINEL_CHECKER_MODEL") or DEFAULT_CHECKER_MODEL,
    }


def _fail_on_minor():
    return os.environ.get("DOC_SENTINEL_FAIL_ON_MINOR", "").lower() == "true"


def _generate_gemini(prompt, model, log):
    """Call Gemini, retrying twice on rate limits (HTTP 429)."""
    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt
            )
            return response.text
        except Exception as e:
            if "429" in str(e) and attempt < 2:
                log("Rate limited, retrying in 30 seconds...")
                time.sleep(30)
            else:
                raise


# Provider name -> function(prompt, model, log) returning the model's text.
# To swap the checker to another vendor, add an entry here and set
# DOC_SENTINEL_CHECKER_PROVIDER to its name.
PROVIDERS = {
    "gemini": _generate_gemini,
}


def run_checker(prompt, log=print):
    """
    Send an audit prompt to the configured checker model and return its text.

    `log` receives progress messages. The MCP server passes a stderr logger,
    because stdout carries the MCP protocol.
    """
    settings = checker_settings()
    generate = PROVIDERS.get(settings["provider"])
    if generate is None:
        raise ValueError(
            "Unknown checker provider '" + settings["provider"] + "'. "
            "Supported: " + ", ".join(sorted(PROVIDERS))
        )
    return generate(prompt, settings["model"], log)


# --- AI-READABILITY SCORING ---------------------------------------------------

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


# --- CODE-TO-DOC MAPPING ------------------------------------------------------

def match_key(path):
    """Normalize a file path for name-based matching: auth_service.py -> auth-service."""
    base_name = os.path.basename(path)
    return os.path.splitext(base_name)[0].lower().replace("_", "-")


def match_docs_by_file(md_files, changed_files):
    """
    For each changed file, list the .md files whose base names match it.

    A doc matches when either normalized base name contains the other.
    Changed files with no match map to an empty list.
    """
    matches = {}
    for changed_file in changed_files:
        base_name = match_key(changed_file)
        matches[changed_file] = [
            md_file for md_file in md_files
            if base_name in match_key(md_file) or match_key(md_file) in base_name
        ]
    return matches


def match_docs(md_files, changed_files):
    """
    Multi-file support: For each changed code file, find matching .md files
    by comparing base names. Falls back to getting-started.md if no match found.
    """
    matched_docs = set()

    for changed_file, docs in match_docs_by_file(md_files, changed_files).items():
        for md_file in docs:
            matched_docs.add(md_file)
        if not docs:
            matched_docs.add(FALLBACK_DOC)

    return list(matched_docs) if matched_docs else [FALLBACK_DOC]


def list_repo_md_files(repo, ref="main"):
    """Recursively list every .md path in a PyGithub repository."""
    all_md_files = []
    contents = repo.get_contents("", ref=ref)
    stack = list(contents)
    while stack:
        item = stack.pop()
        if item.type == "dir":
            stack.extend(repo.get_contents(item.path, ref=ref))
        elif item.path.endswith(".md"):
            all_md_files.append(item.path)
    return all_md_files


# --- DIFFS --------------------------------------------------------------------

def format_diff(file_patches):
    """
    Join (filename, patch) pairs into the diff text the audit prompt expects.

    Files without a patch (binary files, pure renames) are skipped. Returns the
    diff text and the list of files that contributed to it.
    """
    diff_text = ""
    affected_files = []
    for filename, patch in file_patches:
        if patch:
            diff_text += "File: " + filename + "\n" + patch + "\n\n"
            affected_files.append(filename)
    return diff_text, affected_files


# --- AUDIT PROMPTS ------------------------------------------------------------

def build_pr_audit_prompt(diff, doc_content, doc_path, score):
    """Prompt for a drift + style audit of one doc against a code diff."""
    return (
        "You are a Senior Technical Writer reviewing a pull request. "
        "Perform a two-part audit and respond in this exact format:\n\n"
        "**DRIFT AUDIT**\n"
        "Start with YES or NO in bold. One sentence explaining what drifted and why it matters.\n"
        "If YES, assign a severity label on the next line:\n"
        "- 🔴 CRITICAL — drift that would break an AI agent or cause a production incident "
        "(wrong function signatures, deprecated endpoints, missing required parameters, broken auth flows)\n"
        "- 🟡 MINOR — drift that is inaccurate but recoverable by a human "
        "(outdated examples, wrong variable names, minor description mismatches)\n"
        "Then provide the corrected Markdown snippet under a heading called Suggested Fix.\n\n"
        "**STYLE AUDIT**\n"
        "Two to three bullet points maximum. Each bullet is one specific, actionable suggestion. "
        "No preamble. No summary. No encouragement. Just the fixes.\n\n"
        "The document currently has an AI-Readability score of " + str(score) + "%.\n\n"
        "CODE DIFF:\n" + diff + "\n\n"
        "EXISTING DOCS (" + doc_path + "):\n" + doc_content
    )


def build_issue_audit_prompt(doc_content, failure_summary, score):
    """Prompt for a targeted audit of a doc that failed Doc Detective tests."""
    return (
        "You are a Senior Technical Writer. Doc Detective ran automated tests on a documentation file and found failures.\n\n"
        "FAILURE SUMMARY:\n" + failure_summary + "\n\n"
        "Respond in this exact format:\n\n"
        "**FAILURE AUDIT**\n"
        "One sentence identifying what in the documentation is inaccurate or missing that caused these failures.\n"
        "Assign a severity label on the next line:\n"
        "- 🔴 CRITICAL — failure that would break an AI agent or cause a production incident\n"
        "- 🟡 MINOR — failure that is inaccurate but recoverable by a human\n\n"
        "**SUGGESTED FIX**\n"
        "The corrected Markdown snippet only. No explanation before or after it.\n\n"
        "**STYLE AUDIT**\n"
        "Two to three bullet points maximum. Each bullet is one specific, actionable suggestion. "
        "No preamble. No summary. No encouragement. Just the fixes.\n\n"
        "The document currently has an AI-Readability score of " + str(score) + "%.\n\n"
        "EXISTING DOCS:\n" + doc_content
    )


def run_single_doc_audit(diff, doc_content, doc_path, score, log=print):
    """Runs a drift + style audit for a single doc file with severity scoring."""
    return run_checker(build_pr_audit_prompt(diff, doc_content, doc_path, score), log)


def run_issue_audit(doc_content, failure_summary, score, log=print):
    """Runs a targeted audit based on a Doc Detective failure report with severity scoring."""
    return run_checker(build_issue_audit_prompt(doc_content, failure_summary, score), log)


# --- READING THE VERDICT ------------------------------------------------------

def has_drift(audit_result):
    """The GitHub Action's drift rule: the audit text says YES."""
    return "**YES**" in audit_result or audit_result.strip().startswith("YES")


def is_critical(audit_result):
    """The GitHub Action's severity rule: the audit text carries the CRITICAL label."""
    return "🔴 CRITICAL" in audit_result


@dataclass
class DriftVerdict:
    """
    A drift audit read into fields.

    status is "pass" or "fail":
        NO drift              -> pass
        YES + MINOR           -> pass (fail when DOC_SENTINEL_FAIL_ON_MINOR=true)
        YES + CRITICAL        -> fail
        YES, severity missing -> fail
        no YES or NO found    -> fail
    """
    status: str
    drift: bool | None
    severity: str | None
    reason: str
    explanation: str = ""
    suggested_fix: str = ""
    style_notes: list = field(default_factory=list)
    raw: str = ""

    def to_dict(self):
        return asdict(self)


def _heading(name):
    """Match a heading written as **NAME**, ## NAME, or ## **NAME**, with an optional colon."""
    return r'(?:\*\*\s*' + name + r'\s*:?\s*\*\*|(?m:^)#{1,6}\s*(?:\*\*)?\s*' + name + r'\s*(?:\*\*)?):?'


def _section(text, start_heading, end_heading=None):
    """Return the text between two headings such as **DRIFT AUDIT** and **STYLE AUDIT**."""
    start = re.search(_heading(start_heading), text, re.I)
    if not start:
        return None
    rest = text[start.end():]
    if end_heading:
        end = re.search(_heading(end_heading), rest, re.I)
        if end:
            rest = rest[:end.start()]
    return rest.strip()


_SEVERITY_LABEL = r'(?:[Ss]everity\s*:?\s*)?(?:🔴|🟡)?\s*\b(?:CRITICAL|MINOR)\b|🔴|🟡'


def _clean_line(line):
    return line.strip().strip("*-:—– ").strip()


def parse_drift_audit(audit_result, fail_on_minor=None):
    """
    Read a PR drift audit into a DriftVerdict.

    Never more lenient than the GitHub Action: anything has_drift() calls
    drift is drift here too. On top of that, a lowercase or differently bolded
    YES counts as drift, and an answer with no YES or NO fails.
    """
    if fail_on_minor is None:
        fail_on_minor = _fail_on_minor()

    drift_section = _section(audit_result, "DRIFT AUDIT", "STYLE AUDIT")
    if drift_section is None:
        drift_section = audit_result.strip()

    # Split the drift section into the verdict text and the suggested fix.
    fix_match = re.search(r'(?im)^[#*\s]*suggested fix[*:\s]*$', drift_section)
    if fix_match:
        verdict_text = drift_section[:fix_match.start()]
        suggested_fix = drift_section[fix_match.end():].strip()
    else:
        verdict_text = drift_section
        suggested_fix = ""

    answer = re.search(r'(?i)(?:^|\*\*)\s*(yes|no)\b', verdict_text.strip())
    if has_drift(audit_result):
        drift = True
    elif answer:
        drift = answer.group(1).lower() == "yes"
    else:
        drift = None

    severity = None
    if drift:
        if is_critical(audit_result) or re.search(r'\bCRITICAL\b', verdict_text):
            severity = "critical"
        elif "🟡" in verdict_text or re.search(r'\bMINOR\b', verdict_text):
            severity = "minor"

    # Explanation: the verdict lines minus the YES/NO marker and severity label.
    explanation_lines = []
    for line in verdict_text.splitlines():
        line = re.sub(_SEVERITY_LABEL, "", line)
        line = re.sub(r'(?i)^\W*(yes|no)\b\W*', "", line.strip())
        line = _clean_line(line)
        if line:
            explanation_lines.append(line)
    explanation = " ".join(explanation_lines)

    style_section = _section(audit_result, "STYLE AUDIT") or ""
    style_notes = [
        _clean_line(line) for line in style_section.splitlines()
        if re.match(r'\s*[-*•]\s+', line) and _clean_line(line)
    ]

    if drift is None:
        status, reason = "fail", "Could not find a YES or NO verdict in the checker's answer."
    elif not drift:
        status, reason = "pass", "No drift found."
    elif severity == "critical":
        status, reason = "fail", "CRITICAL drift found."
    elif severity == "minor":
        if fail_on_minor:
            status, reason = "fail", "MINOR drift found and DOC_SENTINEL_FAIL_ON_MINOR is set."
        else:
            status, reason = "pass", "MINOR drift found. Passes, but must be listed for the reviewer."
    else:
        status, reason = "fail", "Drift found but the checker gave no severity label."

    return DriftVerdict(
        status=status,
        drift=drift,
        severity=severity,
        reason=reason,
        explanation=explanation,
        suggested_fix=suggested_fix,
        style_notes=style_notes,
        raw=audit_result,
    )


# --- LOCAL CHECKOUTS ----------------------------------------------------------

# Diff drivers that make local hunk headers match GitHub's (see the file).
_GITHUB_DIFF_ATTRIBUTES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "github_diff.gitattributes")


def _git(repo_root, *args):
    result = subprocess.run(
        ["git", "-C", str(repo_root), "-c", "core.quotePath=false",
         "-c", "core.attributesFile=" + _GITHUB_DIFF_ATTRIBUTES, *args],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("git " + " ".join(args) + " failed: " + result.stderr.strip())
    return result.stdout


def validate_diff_range(diff_range):
    """Accept A..B, A...B, or a single commit. Reject anything git would read as an option."""
    if not diff_range or diff_range.startswith("-") or any(c.isspace() for c in diff_range):
        raise ValueError("Invalid diff range: " + repr(diff_range))
    return diff_range


def resolve_doc_path(repo_root, doc_path):
    """Return the absolute path of a doc, refusing paths outside the repository."""
    root = os.path.realpath(repo_root)
    full = os.path.realpath(os.path.join(root, doc_path))
    if full != root and not full.startswith(root + os.sep):
        raise ValueError("Path is outside the repository: " + doc_path)
    return full


def read_local_doc(repo_root, doc_path):
    """Read a doc from the working tree, so uncommitted edits are what gets checked."""
    with open(resolve_doc_path(repo_root, doc_path), encoding="utf-8") as f:
        return f.read()


def doc_sha256(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def list_local_md_files(repo_root):
    """Every tracked or untracked (but not ignored) .md file in a local checkout."""
    out = _git(repo_root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    return sorted({p for p in out.split("\0") if p.endswith(".md")})


def local_file_patches(repo_root, diff_range):
    """
    Return (filename, patch) pairs for a commit range in a local checkout.

    Each patch starts at the first @@ hunk header, which matches the `patch`
    field GitHub's compare API returns, so the audit prompt is the same
    whether the diff came from GitHub or from local git.
    """
    validate_diff_range(diff_range)
    out = _git(repo_root, "diff", "--no-color", "--no-ext-diff", "--find-renames", diff_range, "--")

    patches = []
    blocks = re.split(r'(?m)^(?=diff --git )', out)
    for block in blocks:
        if not block.startswith("diff --git "):
            continue
        lines = block.split("\n")
        filename = None
        old_name = None
        hunk_start = None
        for i, line in enumerate(lines):
            if line.startswith("@@"):
                hunk_start = i
                break
            if line.startswith("rename to "):
                filename = line[len("rename to "):]
            elif line.startswith("+++ b/"):
                # git ends the name with a tab when it contains spaces.
                filename = line[len("+++ b/"):].rstrip("\t")
            elif line.startswith("--- a/"):
                old_name = line[len("--- a/"):].rstrip("\t")
        filename = filename or old_name
        if filename is None:
            # No ---/+++ lines: binary or mode-only change. Take the name from the header.
            filename = lines[0].split(" b/", 1)[-1]
        patch = "\n".join(lines[hunk_start:]).rstrip("\n") if hunk_start is not None else None
        patches.append((filename, patch))
    return patches


def local_diff(repo_root, diff_range):
    """Diff text and affected files for a local commit range."""
    return format_diff(local_file_patches(repo_root, diff_range))


def audit_local_doc(repo_root, diff_range, doc_path, log=print):
    """
    Run the drift check on one doc in a local checkout.

    The doc is read from the working tree and compared against the code
    changes in `diff_range`. Returns a dict with the verdict fields, the
    readability score, and the checker settings used.
    """
    diff, affected_files = local_diff(repo_root, diff_range)
    if not diff:
        raise ValueError("The range " + diff_range + " has no text changes to check against.")

    doc_content = read_local_doc(repo_root, doc_path)
    score = DocSentinelIntelligence(doc_content).calculate_score()
    audit_result = run_single_doc_audit(diff, doc_content, doc_path, score, log=log)
    verdict = parse_drift_audit(audit_result)

    result = verdict.to_dict()
    result.update({
        "doc_path": doc_path,
        # Fingerprint of the exact text checked, so callers can tell whether
        # the doc changed after this verdict.
        "doc_sha256": doc_sha256(doc_content),
        "diff_range": diff_range,
        "affected_files": affected_files,
        "readability_score": score,
        "checker": checker_settings(),
    })
    return result


if __name__ == "__main__":
    # Manual check of one doc in a local checkout:
    #   python src/drift_core.py REPO_PATH RANGE DOC_PATH
    import json
    from dotenv import load_dotenv

    load_dotenv()
    if len(sys.argv) != 4:
        print("Usage: python src/drift_core.py REPO_PATH RANGE DOC_PATH")
        sys.exit(2)
    print(json.dumps(audit_local_doc(*sys.argv[1:]), indent=2, ensure_ascii=False))
