"""
Doc-Sentinel remediation agent.

Updates a repository's docs for a merged PR or a commit range, verifies each
edit with Doc-Sentinel's drift check, and opens a draft PR.

Usage:
    python -m agent --repo PATH --pr NUMBER [--github-repo OWNER/REPO] [options]
    python -m agent --repo PATH --range BASE..HEAD [options]

Options:
    --dry-run          Edit and verify the docs, but do not commit, push, or open the PR.
                       The PR title and body are saved in the run folder instead.
    --model            Agent model (default: claude-opus-5-5, or DOC_SENTINEL_AGENT_MODEL).
    --effort           Agent effort: low, medium, high, xhigh, max (default: high).
    --max-turns        Stop after this many turns (default: 80).
    --max-budget-usd   Stop when the agent's spend reaches this amount.
    --max-attempts     Failed drift checks allowed per doc (default: 3).
    --runs-dir         Where run folders go (default: runs/ in this repository).

Needs ANTHROPIC_API_KEY (the agent), GOOGLE_API_KEY (the drift check), and an
authenticated GitHub CLI (`gh`) for opening the PR.

Exit codes: 0 PR opened, dry run ready, or no changes needed; 2 stopped because
a doc still failed the drift check after the attempt limit; 1 anything else.
"""

import os
import sys
import asyncio
import argparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv  # noqa: E402

from agent.runner import RunConfig, run_agent, EXIT_CODES, DEFAULT_EFFORT, DEFAULT_MAX_TURNS, DEFAULT_MODEL  # noqa: E402


def parse_args(argv=None):
    parser = argparse.ArgumentParser(prog="python -m agent", description="Doc-Sentinel remediation agent")
    parser.add_argument("--repo", required=True, help="Local checkout of the target repository")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--pr", type=int, dest="pr_number", help="Merged pull request number")
    source.add_argument("--range", dest="diff_range", help="Commit range, e.g. BASE..HEAD")
    parser.add_argument("--github-repo", help="OWNER/REPO (default: read from the origin remote)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--model", default=os.environ.get("DOC_SENTINEL_AGENT_MODEL") or DEFAULT_MODEL)
    parser.add_argument("--effort", default=DEFAULT_EFFORT, choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    parser.add_argument("--max-budget-usd", type=float, default=None)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--runs-dir", default=None)
    return parser.parse_args(argv)


def main(argv=None):
    load_dotenv()
    args = parse_args(argv)
    cfg = RunConfig(repo=args.repo, diff_range=args.diff_range, pr_number=args.pr_number,
                    github_repo=args.github_repo, dry_run=args.dry_run, model=args.model, effort=args.effort,
                    max_turns=args.max_turns, max_budget_usd=args.max_budget_usd, max_attempts=args.max_attempts)
    if args.runs_dir:
        cfg.runs_dir = args.runs_dir
    summary = asyncio.run(run_agent(cfg))
    print("\nRun log: " + os.path.join(summary["run_dir"], "report.md"))
    return EXIT_CODES.get(summary["outcome"], 1)


if __name__ == "__main__":
    sys.exit(main())
