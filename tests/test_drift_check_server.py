"""
End-to-end tests for the drift check MCP server.

Each test starts the real server as a stdio subprocess (the way an agent
launches it) against a throwaway git repo built from this repository's sample
docs, with one code change committed. A scripted checker stands in for Gemini
(tests/fake_checker_server.py), so verdicts are fixed and every prompt is recorded.
"""

import os
import sys
import json
import shutil
import asyncio
import subprocess
from contextlib import asynccontextmanager

import pytest
from mcp import ClientSession, StdioServerParameters, stdio_client

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests", "equivalence"))
from src import drift_core  # noqa: E402
from scenarios import REPLY_CRITICAL, REPLY_MINOR, REPLY_NO  # noqa: E402

SAMPLE_FILES = ["src/auth_service.py", "getting-started.md", "api-reference.md",
                "docs/telemetry-guide.md", "README.md", "AI_STYLE_GUIDE.md"]


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def sample_repo(tmp_path):
    """Sample docs at commit 1; auth_service.py changed (AUTH_PATCH) at commit 2."""
    repo = tmp_path / "target"
    for rel in SAMPLE_FILES:
        dest = repo / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(os.path.join(ROOT, rel), dest)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")

    auth = repo / "src" / "auth_service.py"
    text = auth.read_text()
    text = text.replace("def initialize_user_session(user_id, session_timeout):",
                        "def initialize_user_session(user_id, session_timeout, remember_me=False):")
    text = text.replace("{session_timeout}ms timeout", "{session_timeout}s timeout")
    auth.write_text(text)
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "change auth")
    head = git(repo, "rev-parse", "HEAD")
    return repo, base + ".." + head


@asynccontextmanager
async def server_session(tmp_path, repo, args, replies=None, script="tests/fake_checker_server.py", env=None):
    replies_file = tmp_path / "replies.json"
    replies_file.write_text(json.dumps(replies or {}))
    server_env = {
        "PATH": os.environ["PATH"],
        "DOC_SENTINEL_SCRIPTED_REPLIES": str(replies_file),
        "DOC_SENTINEL_SCRIPTED_PROMPTS": str(tmp_path / "prompts.jsonl"),
        "DOC_SENTINEL_CHECKER_MODEL": "scripted-model",
    }
    server_env.update(env or {})
    params = StdioServerParameters(command=sys.executable, args=[os.path.join(ROOT, script), "--repo", str(repo), *args],
                                   env=server_env)
    with open(tmp_path / "server.stderr", "w") as errlog:
        async with stdio_client(params, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


async def call(session, tool, **arguments):
    result = await session.call_tool(tool, arguments)
    if result.is_error:
        return {"error": " ".join(getattr(c, "text", "") for c in result.content)}
    return result.structured_content


def prompts(tmp_path):
    path = tmp_path / "prompts.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def run(coro):
    return asyncio.run(coro)


def test_lists_the_four_tools(tmp_path, sample_repo):
    repo, rng = sample_repo

    async def go():
        async with server_session(tmp_path, repo, ["--range", rng]) as s:
            return sorted(t.name for t in (await s.list_tools()).tools)

    assert run(go()) == ["check_drift", "drift_check_status", "find_candidate_docs", "readability_score"]


def test_find_candidate_docs_uses_the_action_mapping(tmp_path, sample_repo):
    repo, rng = sample_repo

    async def go():
        async with server_session(tmp_path, repo, ["--range", rng]) as s:
            from_range = await call(s, "find_candidate_docs")
            explicit = await call(s, "find_candidate_docs", changed_files=["src/telemetry.py", "src/api_reference.py"])
            return from_range, explicit

    from_range, explicit = run(go())
    assert from_range["changed_files"] == ["src/auth_service.py"]
    assert from_range["no_name_match"] == ["src/auth_service.py"]
    assert from_range["candidates"] == ["getting-started.md"]
    assert explicit["matches"] == {"src/telemetry.py": ["docs/telemetry-guide.md"],
                                   "src/api_reference.py": ["api-reference.md"]}


def test_readability_score_matches_the_action(tmp_path, sample_repo):
    repo, rng = sample_repo

    async def go():
        async with server_session(tmp_path, repo, ["--range", rng]) as s:
            return await call(s, "readability_score", doc_path="getting-started.md")

    expected = drift_core.DocSentinelIntelligence((repo / "getting-started.md").read_text()).calculate_score()
    assert run(go()) == {"doc_path": "getting-started.md", "score": expected}


def test_check_drift_sends_the_action_prompt_for_the_working_tree_doc(tmp_path, sample_repo):
    repo, rng = sample_repo
    doc = repo / "getting-started.md"
    doc.write_text(doc.read_text() + "\nEdited in the working tree, not committed.\n")

    async def go():
        async with server_session(tmp_path, repo, ["--range", rng], {"getting-started.md": [REPLY_NO]}) as s:
            return await call(s, "check_drift", doc_path="getting-started.md")

    result = run(go())
    assert result["status"] == "pass" and result["drift"] is False
    assert result["checker"] == {"provider": "scripted", "model": "scripted-model"}

    sent = prompts(tmp_path)
    assert len(sent) == 1
    # Diff format is pinned to GitHub's by tests/test_github_diff_parity.py.
    diff, _ = drift_core.local_diff(repo, rng)
    assert diff.startswith("File: src/auth_service.py\n@@ ")
    assert "+def initialize_user_session(user_id, session_timeout, remember_me=False):" in diff
    content = doc.read_text()
    score = drift_core.DocSentinelIntelligence(content).calculate_score()
    assert sent[0]["prompt"] == drift_core.build_pr_audit_prompt(diff, content, "getting-started.md", score)
    assert "Edited in the working tree" in sent[0]["prompt"]


def test_three_failed_checks_lock_the_doc(tmp_path, sample_repo):
    repo, rng = sample_repo

    async def go():
        async with server_session(tmp_path, repo, ["--range", rng], {"getting-started.md": [REPLY_CRITICAL]}) as s:
            return [await call(s, "check_drift", doc_path="getting-started.md") for _ in range(4)]

    results = run(go())
    assert [r["status"] for r in results] == ["fail", "fail", "fail", "limit_reached"]
    assert [r.get("attempts_remaining") for r in results[:3]] == [2, 1, 0]
    assert [r["limit_reached"] for r in results] == [False, False, True, True]
    assert results[0]["severity"] == "critical"
    assert "initialize_user_session" in results[0]["suggested_fix"]
    assert len(prompts(tmp_path)) == 3, "the 4th call must not reach the checker"


def test_minor_drift_passes_and_is_listed(tmp_path, sample_repo):
    repo, rng = sample_repo
    replies = {"api-reference.md": [REPLY_CRITICAL, REPLY_MINOR], "getting-started.md": [REPLY_NO]}

    async def go():
        async with server_session(tmp_path, repo, ["--range", rng, "--state-file", str(tmp_path / "state.json")],
                                  replies) as s:
            first = await call(s, "check_drift", doc_path="api-reference.md")
            second = await call(s, "check_drift", doc_path="api-reference.md")
            await call(s, "check_drift", doc_path="getting-started.md")
            return first, second, await call(s, "drift_check_status")

    first, second, status = run(go())
    assert (first["status"], first["severity"]) == ("fail", "critical")
    assert (second["status"], second["severity"]) == ("pass", "minor")
    assert second["attempts_remaining"] == 2
    assert status["all_passing"] is True
    assert status["minor_items"] == [{"doc_path": "api-reference.md", "explanation": second["explanation"]}]
    assert "cli_crashed" in second["explanation"]

    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["all_passing"] is True and len(saved["checks"]["api-reference.md"]) == 2


def test_fail_on_minor_setting(tmp_path, sample_repo):
    repo, rng = sample_repo

    async def go():
        async with server_session(tmp_path, repo, ["--range", rng], {"api-reference.md": [REPLY_MINOR]},
                                  env={"DOC_SENTINEL_FAIL_ON_MINOR": "true"}) as s:
            return await call(s, "check_drift", doc_path="api-reference.md")

    assert run(go())["status"] == "fail"


def test_rejects_paths_outside_the_repo_and_other_ranges(tmp_path, sample_repo):
    repo, rng = sample_repo

    async def go():
        async with server_session(tmp_path, repo, ["--range", rng]) as s:
            return (await call(s, "check_drift", doc_path="../../etc/passwd"),
                    await call(s, "check_drift", doc_path="getting-started.md", diff_range="HEAD~1..HEAD"),
                    await call(s, "readability_score", doc_path="/etc/passwd"))

    outside, other_range, absolute = run(go())
    assert "outside the repository" in outside["error"]
    assert "pinned to the range" in other_range["error"]
    assert "outside the repository" in absolute["error"]
    assert prompts(tmp_path) == []


def test_unpinned_server_requires_a_valid_range(tmp_path, sample_repo):
    repo, rng = sample_repo

    async def go():
        async with server_session(tmp_path, repo, [], {"getting-started.md": [REPLY_NO]}) as s:
            return (await call(s, "check_drift", doc_path="getting-started.md"),
                    await call(s, "check_drift", doc_path="getting-started.md", diff_range="--output=/tmp/x"),
                    await call(s, "check_drift", doc_path="getting-started.md", diff_range=rng))

    missing, option, ok = run(go())
    assert "diff_range is required" in missing["error"]
    assert "Invalid diff range" in option["error"]
    assert ok["status"] == "pass"


def test_missing_gemini_key_is_an_error_not_an_attempt(tmp_path, sample_repo):
    repo, rng = sample_repo

    async def go():
        async with server_session(tmp_path, repo, ["--range", rng], script="mcp_servers/drift_check_server.py",
                                  env={"DOC_SENTINEL_CHECKER_MODEL": ""}) as s:
            err = await call(s, "check_drift", doc_path="getting-started.md")
            return err, await call(s, "drift_check_status")

    err, status = run(go())
    assert "GOOGLE_API_KEY is not set" in err["error"]
    assert status["docs"] == {}
