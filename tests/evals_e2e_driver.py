"""
Run eval cases through the real harness for a test, with the scripted checker.

Usage: python tests/evals_e2e_driver.py CONFIG_JSON
CONFIG_JSON keys: cases (names), out_dir, replies_path, prompts_path.
The model is whatever ANTHROPIC_BASE_URL points at (tests/fake_anthropic_api.py).
"""

import os
import sys
import json
import asyncio

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from evals.harness import load_cases, run_cases  # noqa: E402
from evals.run_evals import write_report  # noqa: E402

cfg = json.load(open(sys.argv[1], encoding="utf-8"))
results = asyncio.run(run_cases(
    load_cases(only=cfg["cases"]), cfg["out_dir"], max_turns=30,
    drift_server_command=[sys.executable, os.path.join(ROOT, "tests", "fake_checker_server.py")],
    drift_server_env={"DOC_SENTINEL_SCRIPTED_REPLIES": cfg["replies_path"],
                      "DOC_SENTINEL_SCRIPTED_PROMPTS": cfg["prompts_path"]},
))
write_report(results, cfg["out_dir"], {"model": "scripted", "effort": "-", "graders": ["deterministic"], "started": "-"})
