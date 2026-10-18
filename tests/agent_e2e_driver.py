"""
Run the real agent runner once for an end-to-end test.

Usage: python tests/agent_e2e_driver.py CONFIG_JSON

CONFIG_JSON keys: repo, diff_range, dry_run, github_repo, runs_dir, run_id,
max_turns, replies_path, prompts_path. The drift check server is the real
server with a scripted checker (tests/fake_checker_server.py). The model is
whatever ANTHROPIC_BASE_URL points at (tests/fake_anthropic_api.py).
Writes the run summary to <runs_dir>/<run_id>/summary.json, as every run does.
"""

import os
import sys
import json
import asyncio

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from agent.runner import RunConfig, run_agent  # noqa: E402

cfg_in = json.load(open(sys.argv[1], encoding="utf-8"))
cfg = RunConfig(
    repo=cfg_in["repo"], diff_range=cfg_in["diff_range"], dry_run=cfg_in.get("dry_run", False),
    github_repo=cfg_in.get("github_repo"), runs_dir=cfg_in["runs_dir"], run_id=cfg_in["run_id"],
    max_turns=cfg_in.get("max_turns", 40), echo=True, model="claude-opus-5-5",
    drift_server_command=[sys.executable, os.path.join(ROOT, "tests", "fake_checker_server.py")],
    drift_server_env={
        "DOC_SENTINEL_SCRIPTED_REPLIES": cfg_in["replies_path"],
        "DOC_SENTINEL_SCRIPTED_PROMPTS": cfg_in["prompts_path"],
        "DOC_SENTINEL_CHECKER_MODEL": "scripted-model",
    },
)
summary = asyncio.run(run_agent(cfg))
print("OUTCOME " + summary["outcome"])
