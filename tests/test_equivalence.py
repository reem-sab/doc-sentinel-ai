"""
Runs the before/after comparison (tests/equivalence/compare_audit.py) as part
of the test suite, and checks that the checker model setting reaches both
scripts.
"""

import os
import sys
import json
import subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HERE = os.path.join(ROOT, "tests", "equivalence")
sys.path.insert(0, HERE)
import compare_audit  # noqa: E402
from scenarios import SCENARIOS, HISTORICAL_SCENARIOS  # noqa: E402


def test_audit_py_matches_baseline():
    assert compare_audit.compare_target("audit", compare_audit.DEFAULT_BASELINE, None) == 0


def test_historical_audit_matches_baseline():
    assert compare_audit.compare_target("historical", compare_audit.DEFAULT_BASELINE, None) == 0


def _models_used(script, scenario, tmp_path):
    scenario = dict(scenario, files=compare_audit.baseline_tree(compare_audit.DEFAULT_BASELINE))
    scenario["env"] = dict(scenario.get("env", {}), DOC_SENTINEL_CHECKER_MODEL="gemini-2.5-pro")
    # run_audit_with_fakes clears checker settings, then applies scenario env.
    result = compare_audit.run_once(os.path.join(ROOT, script), scenario, "0", str(tmp_path))
    return {call["model"] for call in result["gemini_calls"]}


def test_checker_model_setting_applies_to_both_scripts(tmp_path):
    assert _models_used("src/audit.py", SCENARIOS["pr_multi_file_mixed"], tmp_path) == {"gemini-2.5-pro"}
    assert _models_used("historical_audit.py", HISTORICAL_SCENARIOS["hist_all_docs"], tmp_path) == {"gemini-2.5-pro"}
