"""
In-process tools for the agent: read the code diff and open the draft PR.

    git_diff       The changes in the run's fixed commit range.
    open_draft_pr  Commit the doc edits, push a branch, and open a draft PR.

open_draft_pr checks the drift check server's recorded verdicts before doing
anything (see pr_gate_problems), and builds the PR body itself so the
per-doc drift results and the MINOR items always come from the checker,
not from the model.
"""

import os
import re
import json
import shutil
import hashlib
import subprocess

from claude_agent_sdk import tool, create_sdk_mcp_server

# Longest diff returned in one call. Larger diffs ask for a path filter instead
# of being cut silently.
MAX_DIFF_CHARS = 150_000


def _text(text, is_error=False):
    result = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["is_error"] = True
    return result


def _sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# --- PR gate ------------------------------------------------------------------

def pr_gate_problems(ctx, changes):
    """
    Everything that must be true before a PR opens. Returns a list of problems;
    an empty list means the PR may open.

    - At least one doc changed, and nothing but docs changed.
    - Every changed doc has a latest drift check of "pass" on its current content.
    - No doc hit the failed-attempt limit.
    - The `changes` list describes exactly the changed docs.
    """
    problems = []
    changed = ctx.changed_paths()
    docs = [p for p in changed if ctx.is_doc_path(p)]
    non_docs = [p for p in changed if not ctx.is_doc_path(p)]
    state = ctx.drift_state()

    if non_docs:
        problems.append("Files other than docs changed: " + ", ".join(non_docs) + ". Only docs may be in this PR.")
    if not docs:
        problems.append("No doc changes to open a PR for.")

    for doc_path, info in state.get("docs", {}).items():
        if info.get("limit_reached"):
            problems.append(doc_path + " reached the failed drift check limit. The run must stop and report.")

    for doc_path in docs:
        info = state.get("docs", {}).get(doc_path)
        if info is None:
            problems.append(doc_path + " was edited but never drift-checked. Run check_drift on it.")
            continue
        if info["latest_status"] != "pass":
            problems.append(doc_path + " failed its latest drift check. Fix it and check again.")
        full = os.path.join(ctx.repo_root, doc_path)
        if os.path.exists(full) and _sha256_file(full) != info.get("latest_doc_sha256"):
            problems.append(doc_path + " changed after its last drift check. Run check_drift on it again.")

    described = [c.get("doc_path") for c in changes]
    for doc_path in docs:
        if doc_path not in described:
            problems.append("No change summary given for " + doc_path + ".")
    for doc_path in described:
        if doc_path not in docs:
            problems.append(str(doc_path) + " is in the change summary but was not changed.")
    for c in changes:
        if not (c.get("what_changed") or "").strip() or not (c.get("why") or "").strip():
            problems.append("Change summary for " + str(c.get("doc_path")) + " needs both what_changed and why.")
    return problems


# --- PR body ------------------------------------------------------------------

def _verdict_text(info):
    if info["latest_status"] != "pass":
        return "FAIL"
    if info.get("latest_severity") == "minor":
        return "PASS with MINOR drift (listed below)"
    return "PASS, no drift"


def build_pr_body(ctx, changes, notes=None):
    """
    Markdown body for the draft PR. Per-doc verdicts and MINOR items come from
    the drift check server's records; the what/why text comes from the agent.
    """
    state = ctx.drift_state()
    docs_state = state.get("docs", {})
    source = "[" + ctx.source + "](" + ctx.source_url + ")" if ctx.source_url else ctx.source

    lines = [
        "This draft PR updates the documentation for " + source + ".",
        "",
        "Doc-Sentinel's agent edited each doc below, then re-checked it with Doc-Sentinel's "
        "drift check against the same code changes. Please review before merging.",
        "",
        "## Changes",
        "",
    ]
    for c in changes:
        info = docs_state.get(c["doc_path"], {})
        lines += [
            "### `" + c["doc_path"] + "`",
            "",
            "**What changed:** " + c["what_changed"].strip(),
            "",
            "**Why:** " + c["why"].strip(),
            "",
            "**Drift check:** " + (_verdict_text(info) if info else "not checked")
            + (" (" + str(info["checks_run"]) + " check" + ("s" if info["checks_run"] != 1 else "") + ")" if info else ""),
            "",
        ]

    minor = state.get("minor_items", [])
    lines += ["## MINOR drift for the reviewer", ""]
    if minor:
        lines += ["These docs pass the drift check, but the checker still flagged MINOR drift. "
                  "Please check each item:", ""]
        lines += ["- `" + m["doc_path"] + "`: " + (m.get("explanation") or "(no explanation given)") for m in minor]
    else:
        lines.append("None. The drift check found no MINOR drift in the edited docs.")
    lines.append("")

    checked_only = [d for d in docs_state if d not in [c["doc_path"] for c in changes]]
    if checked_only:
        lines += ["## Checked and left unchanged", ""]
        lines += ["- `" + d + "`: " + _verdict_text(docs_state[d]) for d in checked_only]
        lines.append("")

    if notes and notes.strip():
        lines += ["## Notes from the agent", "", notes.strip(), ""]

    lines += [
        "## How this was checked",
        "",
        "- Code changes: `" + ctx.diff_range + "`",
        "- Drift checker: `" + ctx.checker + "`, at most " + str(ctx.max_attempts) + " failed checks per doc",
        "- Agent model: `" + ctx.model + "`",
        "- Run ID: `" + ctx.run_id + "` (full log in the run's `report.md`)",
        "",
        "---",
        "*Opened by the [Doc-Sentinel AI](https://reem-sab.github.io/doc-sentinel-ai/) agent.*",
    ]
    return "\n".join(lines) + "\n"


# --- GitHub -------------------------------------------------------------------

def parse_github_repo(remote_url):
    """OWNER/REPO from a git remote URL (https, ssh, or a git proxy path), or None."""
    for pattern in (r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", r"/git/([^/]+)/([^/]+?)(?:\.git)?/?$"):
        m = re.search(pattern, remote_url.strip())
        if m:
            return m.group(1) + "/" + m.group(2)
    return None


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "changes"


def create_draft_pr(github_repo, title, head, base, body, workdir):
    """Open a draft PR with the GitHub REST API through `gh api`. Returns the PR URL."""
    payload_path = os.path.join(workdir, "pr_payload.json")
    with open(payload_path, "w", encoding="utf-8") as f:
        json.dump({"title": title, "head": head, "base": base, "body": body, "draft": True}, f)
    result = subprocess.run(
        ["gh", "api", "repos/" + github_repo + "/pulls", "--method", "POST", "--input", payload_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("gh api failed: " + (result.stderr or result.stdout).strip())
    return json.loads(result.stdout)["html_url"]


# --- Tools --------------------------------------------------------------------

def build_repo_server(ctx):
    """In-process MCP server with git_diff and open_draft_pr, bound to this run."""

    @tool(
        "git_diff",
        "Show the code changes in this run's fixed commit range. stat_only=true lists changed files "
        "with line counts. path limits the diff to one file or folder.",
        {
            "type": "object",
            "properties": {
                "stat_only": {"type": "boolean", "description": "Only list changed files and line counts."},
                "path": {"type": "string", "description": "Limit the diff to this file or folder."},
            },
            "additionalProperties": False,
        },
    )
    async def git_diff(args):
        cmd = ["diff", "--no-color", "--no-ext-diff", "--find-renames"]
        if args.get("stat_only"):
            cmd.append("--stat=200")
        cmd += [ctx.diff_range, "--"]
        path = args.get("path")
        if path:
            if ctx.resolve_in_repo(path) is None or path.startswith("-"):
                return _text("Path is outside the repository: " + path, is_error=True)
            cmd.append(path)
        try:
            out = ctx.git(*cmd)
        except RuntimeError as e:
            return _text(str(e), is_error=True)
        if not out.strip():
            return _text("No changes" + (" under " + path if path else "") + " in " + ctx.diff_range + ".")
        if len(out) > MAX_DIFF_CHARS:
            stat = ctx.git("diff", "--stat=200", ctx.diff_range, "--")
            return _text("The diff is " + str(len(out)) + " characters, too large for one call. "
                         "Call git_diff again with path set to one file or folder.\n\n" + stat)
        return _text(out)

    @tool(
        "open_draft_pr",
        "Commit the doc edits to a new branch and open a draft pull request. Refuses unless every edited "
        "doc passes its latest drift check with no edits since. Call it once, at the end.",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short PR title."},
                "changes": {
                    "type": "array",
                    "description": "One entry per edited doc.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "doc_path": {"type": "string", "description": "Doc path relative to the repo root."},
                            "what_changed": {"type": "string", "description": "What you changed in the doc."},
                            "why": {"type": "string", "description": "The code change that made it necessary."},
                        },
                        "required": ["doc_path", "what_changed", "why"],
                        "additionalProperties": False,
                    },
                },
                "notes": {"type": "string", "description": "Anything else the reviewer should know."},
            },
            "required": ["title", "changes"],
            "additionalProperties": False,
        },
    )
    async def open_draft_pr(args):
        if ctx.pr_url or ctx.dry_run_pr:
            return _text("A PR was already prepared in this run: " + str(ctx.pr_url or "dry run"), is_error=True)
        changes = args.get("changes") or []
        problems = pr_gate_problems(ctx, changes)
        if problems:
            return _text("Cannot open the PR yet:\n- " + "\n- ".join(problems), is_error=True)

        title = args["title"].strip()
        body = build_pr_body(ctx, changes, args.get("notes"))
        ctx.changes = changes
        branch = "doc-sentinel/" + _slug(ctx.source) + "-" + ctx.run_id[-6:]
        with open(os.path.join(ctx.run_dir, "pr_body.md"), "w", encoding="utf-8") as f:
            f.write(body)

        if ctx.dry_run:
            ctx.dry_run_pr = {"title": title, "head": branch, "base": ctx.base_branch, "body_path": "pr_body.md"}
            with open(os.path.join(ctx.run_dir, "pr.json"), "w", encoding="utf-8") as f:
                json.dump(ctx.dry_run_pr, f, indent=2)
            return _text("Dry run: the PR was not opened. Title, branch, and body were saved to the run folder "
                         "(pr.json, pr_body.md). Nothing was committed or pushed.")

        if not ctx.github_repo:
            return _text("Cannot open the PR: the GitHub repository is unknown. Pass --github-repo.", is_error=True)
        if not shutil.which("gh"):
            return _text("Cannot open the PR: the GitHub CLI (gh) is not installed.", is_error=True)
        try:
            docs = [c["doc_path"] for c in changes]
            ctx.git("checkout", "-b", branch)
            ctx.git("add", "--", *docs)
            ctx.git("commit", "-m", "docs: update for " + ctx.source,
                    "-m", "Opened by the Doc-Sentinel agent (run " + ctx.run_id + ").")
            ctx.pr_branch = branch
            ctx.git("push", "-u", "origin", branch)
            ctx.pr_url = create_draft_pr(ctx.github_repo, title, branch, ctx.base_branch, body, ctx.run_dir)
        except RuntimeError as e:
            return _text("Opening the PR failed: " + str(e)
                         + (" The commit is on local branch " + ctx.pr_branch + "." if ctx.pr_branch else ""),
                         is_error=True)
        return _text("Draft PR opened: " + ctx.pr_url)

    return create_sdk_mcp_server(name="repo", version="1.0.0", tools=[git_diff, open_draft_pr])
