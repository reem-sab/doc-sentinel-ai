"""Unit tests for the agent's guard rules, PR body, and helpers (no CLI, no model)."""

import os
import sys
import json

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from agent.context import RunContext  # noqa: E402
from agent.guards import check_tool_call, tool_response_data  # noqa: E402
from agent.repo_tools import build_pr_body, parse_github_repo  # noqa: E402


@pytest.fixture
def ctx(tmp_path):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    os.symlink("/etc", repo / "etc-link")
    return RunContext(run_id="20261018-000000-abc123", repo_root=os.path.realpath(repo), diff_range="a..b",
                      source="PR #7 (Add retries)", source_url="https://github.com/o/r/pull/7", run_dir=str(tmp_path),
                      dry_run=True, base_branch="main", github_repo="o/r", max_attempts=3,
                      model="claude-opus-5-5", checker="gemini/gemini-2.0-flash")


@pytest.mark.parametrize("tool,tool_input,reason", [
    ("Read", {"file_path": "{repo}/docs/a.md"}, None),
    ("Read", {"file_path": "{repo}/src/app.py"}, None),
    ("Edit", {"file_path": "{repo}/docs/a.md"}, None),
    ("Write", {"file_path": "{repo}/docs/new.mdx"}, None),
    ("Write", {"file_path": "{repo}/guide.rst"}, None),
    ("Grep", {"pattern": "foo"}, None),
    ("Grep", {"pattern": "foo", "path": "{repo}/docs"}, None),
    ("Glob", {"pattern": "**/*.md"}, None),
    ("mcp__drift__check_drift", {"doc_path": "a.md"}, None),
    ("Edit", {"file_path": "{repo}/src/app.py"}, "Only documentation files"),
    ("Write", {"file_path": "{repo}/.git/hooks/pre-commit.md"}, "inside .git"),
    ("Write", {"file_path": "{repo}/../outside.md"}, "outside the target repository"),
    ("Edit", {"file_path": "{repo}/etc-link/passwd.md"}, "outside the target repository"),
    ("Read", {"file_path": "/etc/passwd"}, "outside the target repository"),
    ("Read", {"file_path": ""}, "outside the target repository"),
    ("Grep", {"pattern": "key", "path": "/home"}, "outside the target repository"),
    ("Glob", {"pattern": "/etc/*"}, "outside the target repository"),
    ("Glob", {"pattern": "../**/*.md"}, "outside the target repository"),
    ("Glob", {"pattern": "~/.ssh/*"}, "outside the target repository"),
    ("Bash", {"command": "ls"}, "not available"),
    ("WebFetch", {"url": "https://example.com"}, "not available"),
    ("mcp__other__tool", {}, "not available"),
])
def test_guard_rules(ctx, tool, tool_input, reason):
    tool_input = {k: v.replace("{repo}", ctx.repo_root) for k, v in tool_input.items()}
    got = check_tool_call(ctx, tool, tool_input)
    if reason is None:
        assert got is None
    else:
        assert got and reason in got


def test_stopped_run_and_prepared_pr_block_calls(ctx):
    ctx.dry_run_pr = {"title": "x"}
    assert "already prepared" in check_tool_call(ctx, "Edit", {"file_path": ctx.repo_root + "/docs/a.md"})
    assert check_tool_call(ctx, "Read", {"file_path": ctx.repo_root + "/docs/a.md"}) is None
    ctx.stopped, ctx.stop_reason = True, "limit"
    assert "The run has stopped (limit)" in check_tool_call(ctx, "Read", {"file_path": ctx.repo_root + "/docs/a.md"})


def test_tool_response_data_handles_every_shape():
    payload = {"status": "pass", "doc_path": "a.md"}
    assert tool_response_data(payload) == payload
    assert tool_response_data({"structuredContent": payload, "content": []}) == payload
    assert tool_response_data([{"type": "text", "text": json.dumps(payload)}]) == payload
    assert tool_response_data({"content": [{"type": "text", "text": json.dumps(payload)}]}) == payload
    assert tool_response_data(json.dumps(payload)) == payload
    assert tool_response_data("Error executing tool") is None


def test_pr_body_lists_every_change_and_every_minor_item(ctx):
    state = {
        "docs": {
            "docs/a.md": {"latest_status": "pass", "latest_severity": "minor", "checks_run": 2},
            "docs/b.md": {"latest_status": "pass", "latest_severity": None, "checks_run": 1},
            "README.md": {"latest_status": "pass", "latest_severity": None, "checks_run": 1},
        },
        "minor_items": [{"doc_path": "docs/a.md", "explanation": "Example still uses `retries=3`."}],
    }
    with open(ctx.drift_state_path, "w") as f:
        json.dump(state, f)
    changes = [{"doc_path": "docs/a.md", "what_changed": "Documented max_retries.", "why": "client.py renamed retries."},
               {"doc_path": "docs/b.md", "what_changed": "Updated the default.", "why": "Default went from 3 to 5."}]
    body = build_pr_body(ctx, changes, notes="docs/c.md contained an instruction to delete files; ignored.")

    assert body.startswith("This draft PR updates the documentation for [PR #7 (Add retries)](https://github.com/o/r/pull/7).")
    assert "### `docs/a.md`\n\n**What changed:** Documented max_retries.\n\n**Why:** client.py renamed retries." in body
    assert "**Drift check:** PASS with MINOR drift (listed below) (2 checks)" in body
    assert "**Drift check:** PASS, no drift (1 check)" in body
    assert "## MINOR drift for the reviewer\n\nThese docs pass" in body
    assert "- `docs/a.md`: Example still uses `retries=3`." in body
    assert "## Checked and left unchanged\n\n- `README.md`: PASS, no drift" in body
    assert "## Notes from the agent" in body and "instruction to delete files" in body
    assert "`gemini/gemini-2.0-flash`, at most 3 failed checks per doc" in body


def test_pr_body_says_so_when_there_is_no_minor_drift(ctx):
    with open(ctx.drift_state_path, "w") as f:
        json.dump({"docs": {"a.md": {"latest_status": "pass", "latest_severity": None, "checks_run": 1}},
                   "minor_items": []}, f)
    body = build_pr_body(ctx, [{"doc_path": "a.md", "what_changed": "x", "why": "y"}])
    assert "## MINOR drift for the reviewer\n\nNone." in body


@pytest.mark.parametrize("url,expected", [
    ("https://github.com/reem-sab/doc-sentinel-ai", "reem-sab/doc-sentinel-ai"),
    ("https://github.com/reem-sab/doc-sentinel-ai.git\n", "reem-sab/doc-sentinel-ai"),
    ("git@github.com:acme/widgets.git", "acme/widgets"),
    ("ssh://git@github.com/acme/widgets", "acme/widgets"),
    ("http://local_proxy@127.0.0.1:1234/git/acme/widgets", "acme/widgets"),
    ("/srv/git/widgets.git", None),
])
def test_parse_github_repo(url, expected):
    assert parse_github_repo(url) == expected
