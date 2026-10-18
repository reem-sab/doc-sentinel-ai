"""State for one agent run, shared by the repo tools, the guards, and the runner."""

import os
import json
import subprocess
from dataclasses import dataclass, field

# File types the agent may write. Everything else in the repository is read-only.
DOC_EXTENSIONS = (".md", ".mdx", ".rst")


@dataclass
class RunContext:
    run_id: str
    repo_root: str                 # target repository (absolute, real path)
    diff_range: str                # commit range the docs are updated for
    source: str                    # human description, e.g. "PR #12 (Add retries)"
    source_url: str | None         # link to the PR or compare view, when known
    run_dir: str
    dry_run: bool
    base_branch: str               # branch checked out when the run started
    github_repo: str | None        # OWNER/REPO for opening the PR
    max_attempts: int
    model: str
    checker: str                   # "provider/model" of the drift checker
    log: object = None             # RunLog
    pr_url: str | None = None
    pr_branch: str | None = None
    dry_run_pr: dict | None = None
    stopped: bool = False
    stop_reason: str | None = None
    changes: list = field(default_factory=list)

    @property
    def drift_state_path(self):
        return os.path.join(self.run_dir, "drift_state.json")

    def drift_state(self):
        """Verdicts recorded by the drift check MCP server (the source of truth for the PR gate)."""
        try:
            with open(self.drift_state_path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {"docs": {}, "checks": {}, "minor_items": [], "all_passing": False}

    def git(self, *args, check=True):
        result = subprocess.run(["git", "-C", self.repo_root, "-c", "core.quotePath=false", *args],
                                capture_output=True, text=True)
        if check and result.returncode != 0:
            raise RuntimeError("git " + " ".join(args) + " failed: " + result.stderr.strip())
        return result.stdout

    def changed_paths(self):
        """Paths changed in the working tree since the run started (the tree starts clean)."""
        out = self.git("status", "--porcelain", "-z", "--untracked-files=all")
        paths = []
        entries = out.split("\0")
        i = 0
        while i < len(entries):
            entry = entries[i]
            if not entry:
                i += 1
                continue
            status, path = entry[:2], entry[3:]
            paths.append(path)
            if "R" in status or "C" in status:
                i += 1  # the next entry is the rename source
            i += 1
        return sorted(paths)

    def is_doc_path(self, path):
        return path.lower().endswith(DOC_EXTENSIONS)

    def resolve_in_repo(self, path):
        """Absolute real path for `path` (relative to the repo), or None if it is outside the repo."""
        full = os.path.realpath(os.path.join(self.repo_root, path))
        if full == self.repo_root or full.startswith(self.repo_root + os.sep):
            return full
        return None
