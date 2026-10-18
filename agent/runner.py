"""
Runs the Doc-Sentinel remediation agent once.

    1. Preflight: the target repo is clean, the range resolves, keys are present.
    2. Start the agent (Claude Agent SDK) with:
         - built-in Read, Grep, Glob, Edit, Write (no Bash),
         - the drift check MCP server as a separate process, pinned to the range,
         - the in-process repo tools (git_diff, open_draft_pr),
         - guard hooks that log every call and enforce the rules.
    3. Log every message and tool call to the run folder.
    4. Decide the outcome from what actually happened (the drift server's
       records, the PR tool's state), not from the agent's own account.
"""

import os
import sys
import time
import json
import secrets
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone

from claude_agent_sdk import (
    ClaudeAgentOptions, ClaudeSDKClient, AssistantMessage, ResultMessage, TextBlock, ThinkingBlock,
)

from agent.context import RunContext
from agent.guards import ALLOWED_TOOLS, BUILTIN_TOOLS, DRIFT_SERVER, REPO_SERVER, build_hooks
from agent.prompts import SYSTEM_PROMPT, user_prompt
from agent.repo_tools import build_repo_server, parse_github_repo
from agent.run_log import RunLog
from src import drift_core

AGENT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DRIFT_SERVER_SCRIPT = os.path.join(AGENT_ROOT, "mcp_servers", "drift_check_server.py")

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "high"
DEFAULT_MAX_TURNS = 80

# Exit codes for the CLI.
EXIT_CODES = {"pr_opened": 0, "dry_run_ready": 0, "no_changes": 0, "stopped_drift_limit": 2,
              "incomplete": 1, "error": 1}

# Environment the drift check server needs; nothing else is passed through.
_SERVER_ENV_KEYS = ("PATH", "HOME", "GOOGLE_API_KEY", "GEMINI_API_KEY", "HTTPS_PROXY", "HTTP_PROXY",
                    "NO_PROXY", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE",
                    "DOC_SENTINEL_CHECKER_PROVIDER", "DOC_SENTINEL_CHECKER_MODEL", "DOC_SENTINEL_FAIL_ON_MINOR")


@dataclass
class RunConfig:
    repo: str
    diff_range: str | None = None
    pr_number: int | None = None
    github_repo: str | None = None
    dry_run: bool = False
    model: str = DEFAULT_MODEL
    effort: str = DEFAULT_EFFORT
    max_turns: int = DEFAULT_MAX_TURNS
    max_budget_usd: float | None = None
    max_attempts: int = 3
    runs_dir: str = os.path.join(AGENT_ROOT, "runs")
    run_id: str | None = None
    echo: bool = True
    # Command that starts the drift check server, and extra environment for it.
    # Tests swap in a scripted checker this way.
    drift_server_command: list | None = None
    drift_server_env: dict | None = None


class PreflightError(Exception):
    pass


def _git(repo, *args):
    result = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise PreflightError("git " + " ".join(args) + " failed: " + result.stderr.strip())
    return result.stdout.strip()


def resolve_pr(repo, github_repo, number):
    """
    Turn a merged PR into a commit range, the same diff the GitHub Action audits:
    the PR head compared with its merge base on the base branch.
    """
    result = subprocess.run(["gh", "api", "repos/" + github_repo + "/pulls/" + str(number)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise PreflightError("Could not read PR #" + str(number) + ": " + (result.stderr or result.stdout).strip())
    pr = json.loads(result.stdout)
    if not pr.get("merged_at"):
        raise PreflightError("PR #" + str(number) + " is not merged.")
    base_sha, head_sha, merge_sha = pr["base"]["sha"], pr["head"]["sha"], pr["merge_commit_sha"]

    for sha, ref in ((base_sha, None), (head_sha, "pull/" + str(number) + "/head")):
        if subprocess.run(["git", "-C", repo, "cat-file", "-e", sha + "^{commit}"], capture_output=True).returncode:
            fetch = subprocess.run(["git", "-C", repo, "fetch", "--quiet", "origin", ref or sha],
                                   capture_output=True, text=True)
            if fetch.returncode:
                raise PreflightError("Could not fetch " + (ref or sha) + ": " + fetch.stderr.strip())
    if subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor", merge_sha, "HEAD"],
                      capture_output=True).returncode:
        raise PreflightError("The checked-out branch does not contain PR #" + str(number)
                             + "'s merge commit. Check out and pull the branch it was merged into.")
    source = "PR #" + str(number) + " (" + pr["title"] + ")"
    return base_sha + "..." + head_sha, source, pr["html_url"]


def preflight(cfg):
    repo = os.path.realpath(cfg.repo)
    if not os.path.isdir(repo):
        raise PreflightError("Repository not found: " + cfg.repo)
    if os.path.realpath(_git(repo, "rev-parse", "--show-toplevel")) != repo:
        raise PreflightError("--repo must be the top folder of a git repository: " + repo)
    if _git(repo, "status", "--porcelain", "--untracked-files=all"):
        raise PreflightError("The target repository has uncommitted changes. Commit or stash them first, "
                             "so the PR contains only the agent's edits.")
    base_branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")

    github_repo = cfg.github_repo
    if not github_repo:
        remote = subprocess.run(["git", "-C", repo, "remote", "get-url", "origin"], capture_output=True, text=True)
        github_repo = parse_github_repo(remote.stdout) if remote.returncode == 0 else None

    if (cfg.pr_number is None) == (cfg.diff_range is None):
        raise PreflightError("Give exactly one of --pr or --range.")
    if cfg.pr_number is not None:
        if not github_repo:
            raise PreflightError("--pr needs the GitHub repository; pass --github-repo OWNER/REPO.")
        diff_range, source, source_url = resolve_pr(repo, github_repo, cfg.pr_number)
    else:
        diff_range = drift_core.validate_diff_range(cfg.diff_range)
        source, source_url = "commits " + diff_range, None
        if github_repo and ".." in diff_range:
            source_url = "https://github.com/" + github_repo + "/compare/" + diff_range.replace("...", "..").replace("..", "...")
    for end in [p for p in diff_range.replace("...", "..").split("..") if p]:
        _git(repo, "rev-parse", "--verify", "--quiet", end + "^{commit}")

    if not cfg.dry_run:
        if base_branch == "HEAD":
            raise PreflightError("HEAD is detached. Check out a branch to open a PR against, or use --dry-run.")
        if not github_repo:
            raise PreflightError("Cannot tell which GitHub repository to open the PR in; pass --github-repo.")
    if cfg.drift_server_command is None and drift_core.checker_settings()["provider"] == "gemini" \
            and not (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")):
        raise PreflightError("GOOGLE_API_KEY is not set. The drift check (Gemini) needs it.")

    _, changed_files = drift_core.local_diff(repo, diff_range)
    if not changed_files:
        raise PreflightError("The range " + diff_range + " has no text changes.")
    return repo, diff_range, source, source_url, base_branch, github_repo, changed_files


def _new_run_id():
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)


def _drift_server_config(cfg, ctx):
    command = cfg.drift_server_command or [sys.executable, DRIFT_SERVER_SCRIPT]
    env = {k: os.environ[k] for k in _SERVER_ENV_KEYS if os.environ.get(k)}
    env.update(cfg.drift_server_env or {})
    return {
        "type": "stdio",
        "command": command[0],
        "args": command[1:] + ["--repo", ctx.repo_root, "--range", ctx.diff_range,
                               "--max-attempts", str(ctx.max_attempts), "--state-file", ctx.drift_state_path],
        "env": env,
    }


def build_options(cfg, ctx, stderr_path):
    stderr_file = open(stderr_path, "a", encoding="utf-8")
    return ClaudeAgentOptions(
        model=cfg.model,
        effort=cfg.effort,
        thinking={"type": "adaptive", "display": "summarized"},
        system_prompt=SYSTEM_PROMPT,
        cwd=ctx.repo_root,
        tools=list(BUILTIN_TOOLS),
        allowed_tools=list(ALLOWED_TOOLS),
        permission_mode="dontAsk",
        mcp_servers={DRIFT_SERVER: _drift_server_config(cfg, ctx), REPO_SERVER: build_repo_server(ctx)},
        strict_mcp_config=True,
        setting_sources=[],
        hooks=build_hooks(ctx),
        max_turns=cfg.max_turns,
        max_budget_usd=cfg.max_budget_usd,
        stderr=lambda line: (stderr_file.write(line + "\n"), stderr_file.flush()),
    )


def failure_report(ctx, state):
    """Plain-language account of why the run stopped at the attempt limit."""
    lines = []
    for doc_path, info in state.get("docs", {}).items():
        if not info.get("limit_reached"):
            continue
        lines += ["**`" + doc_path + "`** failed the drift check " + str(info["failed_attempts"])
                  + " times (limit " + str(state.get("max_attempts")) + "):", ""]
        for i, check in enumerate(state.get("checks", {}).get(doc_path, []), 1):
            lines.append(str(i) + ". " + check["status"].upper()
                         + (" (" + check["severity"] + ")" if check.get("severity") else "")
                         + ": " + (check.get("explanation") or check.get("reason") or ""))
        last = state["checks"][doc_path][-1]
        if last.get("suggested_fix"):
            lines += ["", "The checker's last suggested fix:", "", last["suggested_fix"]]
        lines.append("")
    others = {d: i for d, i in state.get("docs", {}).items() if not i.get("limit_reached")}
    if others:
        lines += ["Other docs checked in this run:", ""]
        lines += ["- `" + d + "`: " + i["latest_status"].upper()
                  + (" (" + i["latest_severity"] + ")" if i.get("latest_severity") else "") for d, i in others.items()]
        lines.append("")
    changed = ctx.changed_paths()
    if changed:
        lines.append("No PR was opened. The agent's edits are left uncommitted in the working tree for review: "
                     + ", ".join("`" + p + "`" for p in changed) + ".")
    return "\n".join(lines)


async def run_agent(cfg):
    """Run the agent once. Returns the summary dict (also written to the run folder)."""
    run_id = cfg.run_id or _new_run_id()
    run_dir = os.path.join(cfg.runs_dir, run_id)
    log = RunLog(run_dir, echo=cfg.echo)
    started = time.monotonic()
    settings = drift_core.checker_settings()
    summary = {"run_id": run_id, "run_dir": run_dir, "model": cfg.model, "dry_run": cfg.dry_run,
               "checker": settings["provider"] + "/" + settings["model"]}

    try:
        repo, diff_range, source, source_url, base_branch, github_repo, changed_files = preflight(cfg)
    except PreflightError as e:
        summary.update(outcome="error", message=str(e), repo=cfg.repo)
        log.add("run_finished", outcome="error", message=str(e))
        log.write_summary(summary)
        log.write_report(summary)
        return summary

    ctx = RunContext(run_id=run_id, repo_root=repo, diff_range=diff_range, source=source, source_url=source_url,
                     run_dir=run_dir, dry_run=cfg.dry_run, base_branch=base_branch, github_repo=github_repo,
                     max_attempts=cfg.max_attempts, model=cfg.model, checker=summary["checker"], log=log)
    summary.update(repo=repo, diff_range=diff_range, source=source, source_url=source_url,
                   base_branch=base_branch, github_repo=github_repo)
    log.add("run_started", run_id=run_id, repo=repo, diff_range=diff_range, source=source,
            changed_files=changed_files, model=cfg.model, effort=cfg.effort, max_turns=cfg.max_turns,
            max_attempts=cfg.max_attempts, checker=summary["checker"], dry_run=cfg.dry_run,
            tools=ALLOWED_TOOLS)

    result = None
    final_text = None
    try:
        options = build_options(cfg, ctx, os.path.join(run_dir, "cli_stderr.log"))
        async with ClaudeSDKClient(options=options) as client:
            await client.query(user_prompt(source, diff_range, changed_files))
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock) and block.text.strip():
                            final_text = block.text
                            log.add("decision", text=block.text)
                        elif isinstance(block, ThinkingBlock) and block.thinking.strip():
                            log.add("reasoning", text=block.thinking)
                elif isinstance(message, ResultMessage):
                    result = message
    except Exception as e:
        summary.update(outcome="error", message=type(e).__name__ + ": " + str(e))

    state = ctx.drift_state()
    changed_docs = [p for p in ctx.changed_paths() if ctx.is_doc_path(p)] if not ctx.pr_url else \
        [c["doc_path"] for c in ctx.changes]

    if "outcome" in summary:
        pass
    elif ctx.stopped:
        summary.update(outcome="stopped_drift_limit", message=ctx.stop_reason + ". No PR was opened.",
                       failure_report=failure_report(ctx, state))
    elif ctx.pr_url:
        summary.update(outcome="pr_opened", message="Draft PR opened: " + ctx.pr_url)
    elif ctx.dry_run_pr:
        summary.update(outcome="dry_run_ready", message="Dry run: PR body saved to " + os.path.join(run_dir, "pr_body.md"))
    elif result is not None and not result.is_error and not changed_docs:
        summary.update(outcome="no_changes", message="The agent found no doc that needs changes.")
    else:
        why = ("the agent stopped with " + str(len(changed_docs)) + " edited doc(s) and no PR"
               if result is not None and not result.is_error else
               "the session ended early (" + (result.subtype if result else "no result") + ")")
        summary.update(outcome="incomplete", message="Run incomplete: " + why + ".")

    summary.update(
        pr_url=ctx.pr_url, pr_branch=ctx.pr_branch, dry_run_pr=ctx.dry_run_pr, changes=ctx.changes,
        changed_docs=changed_docs, docs=state.get("docs", {}), minor_items=state.get("minor_items", []),
        num_turns=result.num_turns if result else None, cost_usd=result.total_cost_usd if result else None,
        result_subtype=result.subtype if result else None, agent_final_message=final_text,
        duration_s=round(time.monotonic() - started, 1),
    )
    log.add("run_finished", outcome=summary["outcome"], message=summary.get("message"),
            pr_url=ctx.pr_url, num_turns=summary["num_turns"], cost_usd=summary["cost_usd"])
    log.write_summary(summary)
    log.write_report(summary)
    return summary
