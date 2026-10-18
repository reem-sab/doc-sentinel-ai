"""
Tests for the eval harness and grader.

The harness runs end to end here (real runner, SDK, CLI, hooks, MCP servers)
with a scripted model and checker: one run does the right thing and must pass,
one changes a file it should not and must fail. The grader is also tested on
hand-built run artifacts.
"""

import os
import sys
import json
import subprocess

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, os.path.join(ROOT, "tests", "equivalence"))
import fake_anthropic_api  # noqa: E402
from scenarios import REPLY_NO, REPLY_MINOR  # noqa: E402
from evals.graders import DeterministicGrader, RunArtifacts  # noqa: E402
from evals.harness import load_cases, build_repo  # noqa: E402

CONFIG_ROW_OLD = "| `SENTINEL_MAX_RETRIES` | `3` |"
CONFIG_ROW_NEW = "| `SENTINEL_MAX_RETRIES` | `5` |"


def run_harness(tmp_path, turns, replies):
    server, model, url = fake_anthropic_api.start(turns, "{repo}")
    try:
        # The case repo path is only known inside the harness, so tool inputs use paths
        # relative to the agent's working directory (the case repo).
        (tmp_path / "replies.json").write_text(json.dumps(replies))
        cfg = {"cases": ["default-changed"], "out_dir": str(tmp_path / "out"),
               "replies_path": str(tmp_path / "replies.json"), "prompts_path": str(tmp_path / "prompts.jsonl")}
        (tmp_path / "cfg.json").write_text(json.dumps(cfg))
        (tmp_path / "home").mkdir()
        env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path / "home"), "LANG": "C.UTF-8",
               "ANTHROPIC_BASE_URL": url, "ANTHROPIC_API_KEY": "sk-ant-test", "NO_PROXY": "127.0.0.1,localhost",
               "DISABLE_TELEMETRY": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_AUTOUPDATER": "1",
               "DOC_SENTINEL_CHECKER_PROVIDER": "scripted"}
        proc = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "evals_e2e_driver.py"), str(tmp_path / "cfg.json")],
                              env=env, capture_output=True, text=True, timeout=300)
        assert proc.returncode == 0, proc.stdout + proc.stderr
    finally:
        server.shutdown()
    return json.loads((tmp_path / "out" / "results.json").read_text()), (tmp_path / "out" / "report.md").read_text()


def edit_config_turns(also_touch_readme=False):
    turns = [
        [{"text": "Overview of the change."}, {"tool": "mcp__repo__git_diff", "input": {}}],
        [{"text": "The retries default is documented in configuration.md."},
         {"tool": "Read", "input": {"file_path": "docs/configuration.md"}}],
        [{"text": "Update the default."}, {"tool": "Edit", "input": {
            "file_path": "docs/configuration.md", "old_string": CONFIG_ROW_OLD, "new_string": CONFIG_ROW_NEW}}],
        [{"text": "Verify."}, {"tool": "mcp__drift__check_drift", "input": {"doc_path": "docs/configuration.md"}}],
    ]
    changes = [{"doc_path": "docs/configuration.md", "what_changed": "Default 3 -> 5.", "why": "config.py changed it."}]
    if also_touch_readme:
        turns += [
            [{"text": "Also tweak the README."}, {"tool": "Read", "input": {"file_path": "README.md"}}],
            [{"text": "Edit it."}, {"tool": "Edit", "input": {"file_path": "README.md", "old_string": "# Sentinel SDK",
                                                              "new_string": "# Sentinel SDK (retries: 5)"}}],
            [{"text": "Verify."}, {"tool": "mcp__drift__check_drift", "input": {"doc_path": "README.md"}}],
        ]
        changes.append({"doc_path": "README.md", "what_changed": "Title.", "why": "No reason."})
    turns += [
        [{"text": "Open the PR."}, {"tool": "mcp__repo__open_draft_pr", "input": {"title": "Docs: retries default",
                                                                                  "changes": changes}}],
        [{"text": "Done."}],
    ]
    return turns


def test_harness_passes_a_correct_run(tmp_path):
    results, report = run_harness(tmp_path, edit_config_turns(), {"docs/configuration.md": [REPLY_MINOR]})
    case = results["cases"][0]
    assert results["pass_rate"] == 1.0, [c for c in case["checks"] if not c["passed"]]
    assert case["outcome"] == "dry_run_ready"
    names = [c["name"] for c in case["checks"]]
    assert "drift check passed: docs/configuration.md" in names
    assert "MINOR item listed: docs/configuration.md" in names
    assert "**Pass rate: 1/1 (100%)**" in report


def test_harness_fails_a_run_that_changes_an_unexpected_file(tmp_path):
    results, report = run_harness(tmp_path, edit_config_turns(also_touch_readme=True),
                                  {"docs/configuration.md": [REPLY_NO], "README.md": [REPLY_NO]})
    case = results["cases"][0]
    assert results["pass_rate"] == 0.0
    failed = {c["name"]: c["detail"] for c in case["checks"] if not c["passed"]}
    assert failed == {"no other files changed": "unexpected changes: README.md"}
    assert "**Pass rate: 0/1 (0%)**" in report and "unexpected changes: README.md" in report


# --- Grader on hand-built artifacts --------------------------------------------

def artifacts(files, changed, summary, pr_body=None):
    return RunArtifacts(repo="/x", summary=summary, changed_files=changed, pr_body=pr_body, read=files.get)


def test_grader_checks_content_rules_and_verification():
    case = {"expect": {"outcome": "dry_run_ready", "must_change": ["docs/a.md"], "may_change": ["README.md"],
                       "docs": {"docs/a.md": {"must_contain": ["run_audit"], "must_not_contain": ["start_audit"],
                                              "must_match": [r"retries[^\n]*\b5\b"], "must_not_match": [r"(?i)millisecond"]}}}}
    good = artifacts({"docs/a.md": "Call run_audit. retries: 5"}, ["docs/a.md"],
                     {"outcome": "dry_run_ready", "docs": {"docs/a.md": {"latest_status": "pass"}},
                      "minor_items": [{"doc_path": "docs/a.md"}]},
                     pr_body="## Changes\n\n## MINOR drift for the reviewer\n\n- `docs/a.md`: x\n\n## How this was checked\n")
    assert all(c.passed for c in DeterministicGrader().grade(case, good))

    bad = artifacts({"docs/a.md": "Call start_audit. Timeout in milliseconds."}, ["docs/a.md", "src/x.py"],
                    {"outcome": "incomplete", "docs": {}, "minor_items": [{"doc_path": "docs/a.md"}]},
                    pr_body="## MINOR drift for the reviewer\n\nNone.\n")
    failed = sorted(c.name for c in DeterministicGrader().grade(case, bad) if not c.passed)
    assert failed == sorted([
        "outcome", "no other files changed", "docs/a.md contains 'run_audit'",
        "docs/a.md does not contain 'start_audit'", "docs/a.md matches /retries[^\\n]*\\b5\\b/",
        "docs/a.md does not match /(?i)millisecond/", "drift check passed: docs/a.md",
        "drift check passed: src/x.py", "MINOR item listed: docs/a.md",
    ])


def test_every_case_loads_and_its_patch_applies(tmp_path):
    cases = load_cases()
    assert len(cases) >= 7
    for case in cases:
        repo, diff_range = build_repo(case, str(tmp_path / case["name"]))
        changed = subprocess.run(["git", "-C", repo, "diff", "--name-only", diff_range],
                                 capture_output=True, text=True, check=True).stdout.split()
        assert changed and all(p.startswith("src/") for p in changed), case["name"]
        for path in case["expect"].get("docs", {}):
            assert os.path.isfile(os.path.join(repo, path)), (case["name"], path)
