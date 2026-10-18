"""
End-to-end tests of the agent: the real runner, the real Claude Agent SDK and
Claude Code CLI, the real hooks and both MCP servers, with two stand-ins:

    - the model is a scripted fake Messages API (tests/fake_anthropic_api.py),
    - the drift checker is scripted instead of Gemini (tests/fake_checker_server.py).

PRs go to a local bare git remote and a fake `gh` that records the request.
No API keys or network access are needed.
"""

import os
import sys
import json
import stat
import shutil
import subprocess

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, os.path.join(ROOT, "tests", "equivalence"))
import fake_anthropic_api  # noqa: E402
from scenarios import REPLY_CRITICAL, REPLY_MINOR, REPLY_NO  # noqa: E402

if not shutil.which("git"):
    pytest.skip("git is required", allow_module_level=True)

FAKE_GH = """#!/bin/sh
# Records `gh api ... --input FILE` calls and answers like GitHub's create-PR endpoint.
echo "$@" >> "$FAKE_GH_LOG"
while [ $# -gt 0 ]; do
  if [ "$1" = "--input" ]; then cat "$2" >> "$FAKE_GH_LOG.payload"; fi
  shift
done
echo '{"html_url": "https://github.com/acme/widgets/pull/42"}'
"""

OLD_CALL = "`start_ai_audit(api_key)`"
NEW_CALL = "`initialize_user_session(user_id, session_timeout, remember_me=False)`"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def target(tmp_path):
    """Target repo with the sample docs, one code change committed, and a bare origin."""
    remote = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    repo = tmp_path / "target"
    for rel in ["src/auth_service.py", "getting-started.md", "api-reference.md", "docs/telemetry-guide.md"]:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(os.path.join(ROOT, rel), repo / rel)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "dev@example.com")
    git(repo, "config", "user.name", "Dev")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD")
    auth = repo / "src" / "auth_service.py"
    auth.write_text(auth.read_text()
                    .replace("(user_id, session_timeout):", "(user_id, session_timeout, remember_me=False):")
                    .replace("{session_timeout}ms timeout", "{session_timeout}s timeout"))
    git(repo, "commit", "-qam", "Add remember_me; timeout is now in seconds")
    git(repo, "push", "-q", "origin", "main")
    return repo, remote, base + ".." + git(repo, "rev-parse", "HEAD")


def run_scenario(tmp_path, target, turns, replies, dry_run=False, max_turns=40):
    repo, _, diff_range = target
    server, model, url = fake_anthropic_api.start(turns, str(repo))
    try:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        (bin_dir / "gh").write_text(FAKE_GH)
        (bin_dir / "gh").chmod(stat.S_IRWXU)
        home = tmp_path / "home"
        home.mkdir(exist_ok=True)
        (tmp_path / "replies.json").write_text(json.dumps(replies))
        cfg = {"repo": str(repo), "diff_range": diff_range, "dry_run": dry_run, "github_repo": "acme/widgets",
               "runs_dir": str(tmp_path / "runs"), "run_id": "test-run", "max_turns": max_turns,
               "replies_path": str(tmp_path / "replies.json"), "prompts_path": str(tmp_path / "prompts.jsonl")}
        (tmp_path / "cfg.json").write_text(json.dumps(cfg))
        # A clean environment: only what the CLI needs to reach the fake API.
        env = {"PATH": str(bin_dir) + os.pathsep + os.environ["PATH"], "HOME": str(home), "LANG": "C.UTF-8",
               "ANTHROPIC_BASE_URL": url, "ANTHROPIC_API_KEY": "sk-ant-test", "NO_PROXY": "127.0.0.1,localhost",
               "DISABLE_TELEMETRY": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_AUTOUPDATER": "1",
               "DOC_SENTINEL_CHECKER_PROVIDER": "scripted", "DOC_SENTINEL_CHECKER_MODEL": "scripted-model",
               "FAKE_GH_LOG": str(tmp_path / "gh.log")}
        proc = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "agent_e2e_driver.py"),
                               str(tmp_path / "cfg.json")], env=env, capture_output=True, text=True, timeout=300)
        assert proc.returncode == 0, proc.stdout + proc.stderr
    finally:
        server.shutdown()
    run_dir = tmp_path / "runs" / "test-run"
    summary = json.loads((run_dir / "summary.json").read_text())
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
    return summary, model, events, run_dir


def results_for(model, tool):
    return [(is_error, text) for name, is_error, text in model.tool_results() if name == tool]


def test_full_run_opens_a_draft_pr(tmp_path, target):
    repo, remote, diff_range = target
    turns = [
        [{"text": "Start with an overview of the code changes."}, {"tool": "mcp__repo__git_diff", "input": {"stat_only": True}}],
        [{"text": "Read the full diff."}, {"tool": "mcp__repo__git_diff", "input": {}}],
        [{"text": "Get the name-based candidates."}, {"tool": "mcp__drift__find_candidate_docs", "input": {}}],
        [{"text": "Search the docs for the session and audit functions."},
         {"tool": "Grep", "input": {"pattern": "start_ai_audit|initialize_user_session|session_timeout",
                                    "path": "{repo}", "output_mode": "files_with_matches"}}],
        [{"text": "getting-started.md documents the entry point; read it."},
         {"tool": "Read", "input": {"file_path": "{repo}/getting-started.md"}}],
        [{"text": "Replace the old call with the new signature."},
         {"tool": "Edit", "input": {"file_path": "{repo}/getting-started.md", "old_string": OLD_CALL, "new_string": NEW_CALL}}],
        [{"text": "Verify the edit."}, {"tool": "mcp__drift__check_drift", "input": {"doc_path": "getting-started.md"}}],
        [{"text": "The checker still flags it; document the timeout unit."},
         {"tool": "Edit", "input": {"file_path": "{repo}/getting-started.md",
                                    "old_string": "This function requires your API key to authenticate.",
                                    "new_string": "`session_timeout` is in seconds."}}],
        [{"text": "Check again."}, {"tool": "mcp__drift__check_drift", "input": {"doc_path": "getting-started.md"}}],
        [{"text": "Confirm the candidate I left alone."}, {"tool": "mcp__drift__check_drift", "input": {"doc_path": "api-reference.md"}}],
        [{"text": "Everything passes; open the draft PR."},
         {"tool": "mcp__repo__open_draft_pr", "input": {
             "title": "Docs: initialize_user_session signature and timeout unit",
             "changes": [{"doc_path": "getting-started.md",
                          "what_changed": "Replaced start_ai_audit(api_key) with the new session call and stated the timeout unit.",
                          "why": "src/auth_service.py added remember_me and changed the timeout from ms to s."}]}}],
        [{"text": "Done. Updated getting-started.md; api-reference.md needed nothing. PR: https://github.com/acme/widgets/pull/42"}],
    ]
    replies = {"getting-started.md": [REPLY_CRITICAL, REPLY_MINOR], "api-reference.md": [REPLY_NO]}
    summary, model, events, run_dir = run_scenario(tmp_path, target, turns, replies)

    assert summary["outcome"] == "pr_opened"
    assert summary["pr_url"] == "https://github.com/acme/widgets/pull/42"
    assert summary["changed_docs"] == ["getting-started.md"]
    assert summary["docs"]["getting-started.md"]["checks_run"] == 2
    assert summary["docs"]["getting-started.md"]["latest_severity"] == "minor"

    # The PR request: draft, against main, from the agent's branch, with the body built from the checker's records.
    assert "repos/acme/widgets/pulls --method POST" in (tmp_path / "gh.log").read_text()
    payload = json.loads((tmp_path / "gh.log.payload").read_text())
    assert payload["draft"] is True and payload["base"] == "main"
    assert payload["head"].startswith("doc-sentinel/commits-") and payload["head"] == summary["pr_branch"]
    body = payload["body"]
    assert "### `getting-started.md`" in body and "remember_me" in body
    assert "**Drift check:** PASS with MINOR drift (listed below) (2 checks)" in body
    assert "## MINOR drift for the reviewer" in body
    assert "- `getting-started.md`: The dashboard guide still lists two events" in body
    assert "## Checked and left unchanged" in body and "- `api-reference.md`: PASS, no drift" in body

    # The branch reached the remote with exactly one commit that touches only the doc.
    assert git(remote, "log", "--format=%s", "-1", payload["head"]) == "docs: update for commits " + diff_range
    assert git(remote, "diff", "--name-only", "main", payload["head"]) == "getting-started.md"
    assert NEW_CALL in git(remote, "show", payload["head"] + ":getting-started.md")
    assert git(repo, "status", "--porcelain") == ""

    # The run log has every decision, call, and verdict.
    types = [e["type"] for e in events]
    assert types[0] == "run_started" and types[-1] == "run_finished"
    assert types.count("tool_call") == 11 and types.count("drift_check") == 3
    assert [e["status"] for e in events if e["type"] == "drift_check"] == ["fail", "pass", "pass"]
    assert "Replace the old call with the new signature." in [e["text"] for e in events if e["type"] == "decision"]
    report = (run_dir / "report.md").read_text()
    assert "## Timeline" in report and "pr_opened" in report and "drift.check_drift" in report


def test_stops_and_reports_after_three_failed_checks(tmp_path, target):
    repo, remote, _ = target
    edit = lambda old, new: {"tool": "Edit", "input": {"file_path": "{repo}/getting-started.md",
                                                       "old_string": old, "new_string": new}}
    check = {"tool": "mcp__drift__check_drift", "input": {"doc_path": "getting-started.md"}}
    turns = [
        [{"text": "Read the guide."}, {"tool": "Read", "input": {"file_path": "{repo}/getting-started.md"}}],
        [{"text": "First fix."}, edit(OLD_CALL, "`initialize_user_session(user_id)`")],
        [{"text": "Check."}, check],
        [{"text": "Second fix."}, edit("`initialize_user_session(user_id)`", "`initialize_user_session(user_id, t)`")],
        [{"text": "Check."}, check],
        [{"text": "Third fix."}, edit("`initialize_user_session(user_id, t)`", "`initialize_user_session(u, t)`")],
        [{"text": "Check."}, check],
        [{"text": "Try the PR anyway."}, {"tool": "mcp__repo__open_draft_pr", "input": {
            "title": "x", "changes": [{"doc_path": "getting-started.md", "what_changed": "x", "why": "x"}]}}],
        [{"text": "Done."}],
    ]
    summary, model, events, run_dir = run_scenario(tmp_path, target, turns, {"getting-started.md": [REPLY_CRITICAL]})

    assert summary["outcome"] == "stopped_drift_limit"
    assert "getting-started.md after 3 attempts" in summary["message"]
    assert summary["docs"]["getting-started.md"]["failed_attempts"] == 3
    report = summary["failure_report"]
    assert "**`getting-started.md`** failed the drift check 3 times (limit 3)" in report
    assert report.count("FAIL (critical)") == 3 and "initialize_user_session(user_id, session_timeout)" in report
    assert "left uncommitted in the working tree" in report

    # The session ended at the third failed check: the model was never asked for another turn,
    # and nothing was committed, pushed, or opened.
    assert len(model.requests) == 7
    assert not (tmp_path / "gh.log").exists() and not (run_dir / "pr_body.md").exists()
    assert git(repo, "status", "--porcelain") == "M getting-started.md"
    assert git(remote, "branch", "--list", "doc-sentinel/*") == ""
    assert [e["type"] for e in events].count("guard_stop") == 1
    assert "## Failure report" in (run_dir / "report.md").read_text()


def test_guards_and_pr_gate_refuse_unsafe_calls(tmp_path, target):
    repo, _, diff_range = target
    pr_call = {"tool": "mcp__repo__open_draft_pr", "input": {
        "title": "Docs update", "changes": [{"doc_path": "getting-started.md", "what_changed": "New call.",
                                              "why": "Signature changed."}]}}
    check = {"tool": "mcp__drift__check_drift", "input": {"doc_path": "getting-started.md"}}
    turns = [
        [{"text": "Try to change code."}, {"tool": "Write", "input": {"file_path": "{repo}/src/auth_service.py", "content": "x"}}],
        [{"text": "Try to read outside the repo."}, {"tool": "Read", "input": {"file_path": "/etc/hostname"}}],
        [{"text": "Try to escape with a relative path."}, {"tool": "Edit", "input": {
            "file_path": "{repo}/../escape.md", "old_string": "a", "new_string": "b"}}],
        [{"text": "Try a shell."}, {"tool": "Bash", "input": {"command": "ls"}}],
        [{"text": "Try another range."}, {"tool": "mcp__drift__check_drift", "input": {
            "doc_path": "getting-started.md", "diff_range": "HEAD~1..HEAD"}}],
        [{"text": "Read the guide."}, {"tool": "Read", "input": {"file_path": "{repo}/getting-started.md"}}],
        [{"text": "Edit it."}, {"tool": "Edit", "input": {"file_path": "{repo}/getting-started.md",
                                                          "old_string": OLD_CALL, "new_string": NEW_CALL}}],
        [{"text": "Open the PR before checking."}, pr_call],
        [{"text": "Check."}, check],
        [{"text": "One more edit."}, {"tool": "Edit", "input": {"file_path": "{repo}/getting-started.md",
                                                                "old_string": "Getting Started", "new_string": "Getting started"}}],
        [{"text": "Open the PR with a stale check."}, pr_call],
        [{"text": "Check again."}, check],
        [{"text": "Open the PR."}, pr_call],
        [{"text": "Edit after the PR."}, {"tool": "Edit", "input": {"file_path": "{repo}/getting-started.md",
                                                                    "old_string": "Getting started", "new_string": "x"}}],
        [{"text": "Done."}],
    ]
    summary, model, events, run_dir = run_scenario(tmp_path, target, turns, {"getting-started.md": [REPLY_NO]},
                                                   dry_run=True)

    assert summary["outcome"] == "dry_run_ready"
    denied = {e["reason"] for e in events if e["type"] == "tool_denied"}
    assert "Only documentation files (.md, .mdx, .rst) can be written. src/auth_service.py is not one." in denied
    assert "Path is outside the target repository: /etc/hostname" in denied
    assert "The PR is already prepared; the docs can no longer change in this run." in denied
    # The CLI's own path checks refuse ../ escapes before the hook runs; either way it never happens.
    escape = results_for(model, "Edit")[0]
    assert escape[0], escape
    assert not (repo.parent / "escape.md").exists()

    bash = [r for name, err, r in model.tool_results() if name == "Bash"]
    assert bash and "Bash" in bash[0]  # not offered to the agent at all
    other_range = results_for(model, "mcp__drift__check_drift")[0]
    assert other_range[0] and "pinned to the range" in other_range[1]

    gate = results_for(model, "mcp__repo__open_draft_pr")
    assert gate[0][0] and "getting-started.md was edited but never drift-checked" in gate[0][1]
    assert gate[1][0] and "getting-started.md changed after its last drift check" in gate[1][1]
    assert not gate[2][0] and "Dry run: the PR was not opened" in gate[2][1]

    # Dry run: the PR body is saved, nothing is committed, and the doc edits stay in the working tree.
    assert "## MINOR drift for the reviewer" in (run_dir / "pr_body.md").read_text()
    assert json.loads((run_dir / "pr.json").read_text())["base"] == "main"
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert git(repo, "status", "--porcelain") == "M getting-started.md"
    assert not (tmp_path / "gh.log").exists()


def test_no_changes_needed(tmp_path, target):
    turns = [
        [{"text": "Overview."}, {"tool": "mcp__repo__git_diff", "input": {"stat_only": True}}],
        [{"text": "Confirm the API reference."}, {"tool": "mcp__drift__check_drift", "input": {"doc_path": "api-reference.md"}}],
        [{"text": "No doc describes the changed behaviour; nothing to edit."}],
    ]
    summary, model, events, run_dir = run_scenario(tmp_path, target, turns, {"api-reference.md": [REPLY_NO]})
    assert summary["outcome"] == "no_changes"
    assert summary["changed_docs"] == [] and summary["pr_url"] is None
    assert summary["agent_final_message"] == "No doc describes the changed behaviour; nothing to edit."
