"""
Runs one eval case: build the target repo, run the agent on it, grade the result.

A case is a folder under evals/cases/:

    case.yaml     description, optional fixture name, and the `expect` block
    change.patch  the code change, applied as a commit on top of the fixture

The fixture (evals/fixtures/<name>/, default sample-project) is a small
project whose docs are accurate before the change. The agent runs in dry-run
mode, so nothing is pushed; its edits stay in the case's working tree.
"""

import os
import sys
import time
import shutil
import asyncio
import subprocess
from dataclasses import dataclass, field

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from agent.runner import RunConfig, run_agent  # noqa: E402
from evals.graders import GRADERS, RunArtifacts  # noqa: E402

CASES_DIR = os.path.join(ROOT, "evals", "cases")
FIXTURES_DIR = os.path.join(ROOT, "evals", "fixtures")
DEFAULT_FIXTURE = "sample-project"


@dataclass
class CaseResult:
    name: str
    description: str
    passed: bool
    checks: list = field(default_factory=list)
    outcome: str | None = None
    cost_usd: float | None = None
    num_turns: int | None = None
    duration_s: float | None = None
    run_dir: str | None = None
    error: str | None = None


def load_cases(cases_dir=CASES_DIR, only=None):
    cases = []
    for name in sorted(os.listdir(cases_dir)):
        folder = os.path.join(cases_dir, name)
        if not os.path.isfile(os.path.join(folder, "case.yaml")) or (only and name not in only):
            continue
        with open(os.path.join(folder, "case.yaml"), encoding="utf-8") as f:
            case = yaml.safe_load(f)
        case.update(name=name, folder=folder)
        cases.append(case)
    return cases


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo, "-c", "user.email=evals@doc-sentinel.local",
                           "-c", "user.name=Doc-Sentinel evals", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def build_repo(case, workdir):
    """Fixture at commit 1, the case's change at commit 2. Returns (repo, range)."""
    repo = os.path.join(workdir, "repo")
    shutil.copytree(os.path.join(FIXTURES_DIR, case.get("fixture", DEFAULT_FIXTURE)), repo)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "Fixture")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "apply", "--whitespace=nowarn", os.path.join(case["folder"], "change.patch"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", case.get("description", case["name"]).strip())
    return repo, base + ".." + _git(repo, "rev-parse", "HEAD")


def _artifacts(repo, summary):
    # Not _git(): its strip() would eat the leading space of the first status entry.
    out = subprocess.run(["git", "-C", repo, "-c", "core.quotePath=false", "status", "--porcelain", "-z",
                          "--untracked-files=all"], check=True, capture_output=True, text=True).stdout
    entries, changed, i = out.split("\0"), [], 0
    while i < len(entries):
        if len(entries[i]) > 3:
            changed.append(entries[i][3:])
            if entries[i][0] in "RC":
                i += 1  # the next entry is the rename source, with no status prefix
        i += 1
    changed.sort()

    def read(path):
        full = os.path.join(repo, path)
        if not os.path.isfile(full):
            return None
        with open(full, encoding="utf-8") as f:
            return f.read()

    body_path = os.path.join(summary.get("run_dir", ""), "pr_body.md")
    pr_body = open(body_path, encoding="utf-8").read() if os.path.isfile(body_path) else None
    return RunArtifacts(repo=repo, summary=summary, changed_files=changed, pr_body=pr_body, read=read)


async def run_case(case, out_dir, graders=("deterministic",), **run_overrides):
    """Run and grade one case. run_overrides go to RunConfig (model, effort, max_turns, ...)."""
    workdir = os.path.join(out_dir, case["name"])
    os.makedirs(workdir, exist_ok=True)
    started = time.monotonic()
    result = CaseResult(name=case["name"], description=(case.get("description") or "").strip(), passed=False)
    try:
        repo, diff_range = build_repo(case, workdir)
        cfg = RunConfig(repo=repo, diff_range=diff_range, dry_run=True, runs_dir=os.path.join(workdir, "runs"),
                        run_id="run", echo=False, **run_overrides)
        summary = await run_agent(cfg)
        run = _artifacts(repo, summary)
        for name in graders:
            result.checks += GRADERS[name]().grade(case, run)
        result.passed = bool(result.checks) and all(c.passed for c in result.checks)
        result.outcome = summary.get("outcome")
        result.cost_usd = summary.get("cost_usd")
        result.num_turns = summary.get("num_turns")
        result.run_dir = summary.get("run_dir")
    except Exception as e:
        result.error = type(e).__name__ + ": " + str(e)
    result.duration_s = round(time.monotonic() - started, 1)
    return result


async def run_cases(cases, out_dir, jobs=1, graders=("deterministic",), progress=None, **run_overrides):
    """Run cases with at most `jobs` at a time. Results come back in case order."""
    semaphore = asyncio.Semaphore(max(1, jobs))

    async def one(case):
        async with semaphore:
            result = await run_case(case, out_dir, graders, **run_overrides)
            if progress:
                progress(result)
            return result

    return await asyncio.gather(*(one(c) for c in cases))
