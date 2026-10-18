"""
The local diff (used by the MCP server) must match the diff the GitHub Action
builds from the compare API, so both send the checker the same prompt.

Compares the two for this repository's merged pull requests. Needs network
access, `gh` signed in, and enough git history; skips otherwise.
"""

import os
import sys
import json
import shutil
import subprocess

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from src import drift_core  # noqa: E402

REPO = "reem-sab/doc-sentinel-ai"
# (pull request, base sha, merge commit) for merged PRs in this repository.
MERGED_PRS = [
    (4, "3dcd46f90a", "b94c2f0e48"),
    (5, "b94c2f0e48", "c94f43d680"),
    (6, "c94f43d680", "d7ff2416fc"),
]


def _have_commit(sha):
    return subprocess.run(["git", "-C", ROOT, "cat-file", "-e", sha + "^{commit}"],
                          capture_output=True).returncode == 0


@pytest.mark.parametrize("number,base,head", MERGED_PRS)
def test_local_diff_matches_github_compare(number, base, head):
    if not shutil.which("gh") or os.environ.get("SKIP_NETWORK_TESTS"):
        pytest.skip("gh not available")
    if not (_have_commit(base) and _have_commit(head)):
        pytest.skip("commits not in local history; run git fetch --depth=200 origin main")
    api = subprocess.run(["gh", "api", "repos/" + REPO + "/compare/" + base + "..." + head],
                         capture_output=True, text=True)
    if api.returncode != 0:
        pytest.skip("GitHub API unavailable: " + api.stderr.strip()[:200])

    files = json.loads(api.stdout)["files"]
    github_diff = drift_core.format_diff((f["filename"], f.get("patch")) for f in files)
    local = drift_core.local_diff(ROOT, base + "..." + head)

    assert local[1] == github_diff[1], "affected files differ"
    assert local[0] == github_diff[0], "diff text differs"
