"""
Check that the refactored src/audit.py and historical_audit.py behave exactly
like the originals.

Runs every scenario twice, once with the script from a baseline commit and
once with the working-tree script, and compares everything each run produced.

Usage:
    python tests/equivalence/compare_audit.py [--target audit|historical|all]
        [--baseline COMMIT] [--show SCENARIO]

    --target    Which script to compare (default: all).
    --baseline  Commit holding the original scripts (default: b3d3c84, the
                last commit before drift_core.py was extracted).
    --show      Print the comment or report a scenario produced.
"""

import os
import re
import sys
import json
import argparse
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
from scenarios import SCENARIOS, HISTORICAL_SCENARIOS  # noqa: E402

DEFAULT_BASELINE = "b3d3c84"
HASH_SEEDS = ["0", "4242"]   # set order decides doc order; check more than one

TARGETS = {
    "audit": ("src/audit.py", SCENARIOS),
    "historical": ("historical_audit.py", HISTORICAL_SCENARIOS),
}


def git(*args):
    return subprocess.run(["git", "-C", REPO_ROOT, *args], capture_output=True, check=True).stdout


def baseline_tree(commit):
    """Every text file at the baseline commit: path -> content."""
    files = {}
    for path in git("ls-tree", "-r", "--name-only", commit).decode().splitlines():
        try:
            files[path] = git("show", commit + ":" + path).decode("utf-8")
        except UnicodeDecodeError:
            continue
    return files


def run_once(audit_path, scenario, seed, workdir):
    scenario_path = os.path.join(workdir, "scenario.json")
    output_path = os.path.join(workdir, "output.json")
    with open(scenario_path, "w", encoding="utf-8") as f:
        json.dump(scenario, f)
    env = dict(os.environ, PYTHONHASHSEED=seed)
    subprocess.run(
        [sys.executable, os.path.join(HERE, "run_audit_with_fakes.py"), audit_path, scenario_path, output_path],
        env=env, check=True, cwd=REPO_ROOT,
    )
    with open(output_path, encoding="utf-8") as f:
        result = json.load(f)
    # Known, intended difference: the original historical_audit.py built one
    # Gemini client per run (even when it then audited nothing); through
    # drift_core it builds one per check, as audit.py always has. Compare
    # which API key was used, not how many client objects were made.
    if "report_file" in result or "argv" in scenario:
        result["gemini_api_keys"] = sorted(set(result.get("gemini_api_keys", []))) if result["gemini_calls"] else []
    # The historical report is stamped with the current minute.
    if "report_file" in result:
        result["report_file"] = re.sub(r"\*\*Date:\*\* .*", "**Date:** <now>", result["report_file"])
    return result


def first_difference(a, b, path="result"):
    if type(a) is not type(b):
        return path + ": " + repr(a)[:120] + " != " + repr(b)[:120]
    if isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                return path + "." + key + " only on one side"
            diff = first_difference(a[key], b[key], path + "." + key)
            if diff:
                return diff
    elif isinstance(a, list):
        if len(a) != len(b):
            return path + ": length " + str(len(a)) + " != " + str(len(b))
        for i, (x, y) in enumerate(zip(a, b)):
            diff = first_difference(x, y, path + "[" + str(i) + "]")
            if diff:
                return diff
    elif a != b:
        return path + ": " + repr(a)[:200] + " != " + repr(b)[:200]
    return None


def summarize(result):
    label = ""
    for line in result["github_output"].splitlines():
        if line.startswith("audit_label="):
            label = line.split("=", 1)[1]
    events = [e[0] for e in result["telemetry"] if e[0] != "flush"]
    if "report_file" in result:
        label = "report " + str(len(result["report_file"])) + " chars"
    return {
        "exit": result["exit_code"],
        "label": label or "-",
        "gemini_calls": len(result["gemini_calls"]),
        "comments": len(result["comments"]),
        "events": ",".join(events),
    }


def compare_target(target, baseline, show):
    script, scenarios = TARGETS[target]
    files = baseline_tree(baseline)
    failures = 0

    with tempfile.TemporaryDirectory() as tmp:
        baseline_script = os.path.join(tmp, "baseline", os.path.basename(script))
        os.makedirs(os.path.dirname(baseline_script))
        with open(baseline_script, "wb") as f:
            f.write(git("show", baseline + ":" + script))
        current_script = os.path.join(REPO_ROOT, script)

        print("\n== " + script + "   baseline: " + baseline + "   current: working tree")
        header = "{:<28} {:<9} {:<5} {:<22} {:>5} {:>8}  {}".format(
            "scenario", "result", "exit", "label / report", "calls", "comments", "telemetry")
        print(header)
        print("-" * len(header))

        for name, sc in scenarios.items():
            scenario = dict(sc, files={p: c for p, c in files.items() if p not in sc.get("drop_files", [])})
            verdicts = []
            for seed in HASH_SEEDS:
                old = run_once(baseline_script, scenario, seed, tmp)
                new = run_once(current_script, scenario, seed, tmp)
                verdicts.append(first_difference(old, new))
            diff = next((d for d in verdicts if d), None)
            failures += bool(diff)
            s = summarize(new)
            print("{:<28} {:<9} {:<5} {:<22} {:>5} {:>8}  {}".format(
                name, "IDENTICAL" if not diff else "DIFFERENT", str(s["exit"]), s["label"],
                s["gemini_calls"], s["comments"], s["events"]))
            if diff:
                print("    first difference: " + diff)
            if show == name:
                for c in new["comments"]:
                    print("\n--- comment posted on " + c["on"] + " ---\n" + c["body"] + "\n--- end ---\n")
                if "report_file" in new:
                    print("\n--- stdout ---\n" + new["stdout"] + "--- report ---\n" + new["report_file"] + "\n--- end ---\n")

    print(str(len(scenarios) - failures) + "/" + str(len(scenarios)) + " " + script
          + " scenarios identical (each run with PYTHONHASHSEED " + " and ".join(HASH_SEEDS) + ")")
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--target", choices=["audit", "historical", "all"], default="all")
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--show", default=None)
    args = parser.parse_args()

    print("Compared per run: stdout, exit code, PR/issue comments, GITHUB_OUTPUT, report file,")
    print("telemetry, every prompt sent to the model (+ model name), sleeps, GitHub refs read.")
    targets = list(TARGETS) if args.target == "all" else [args.target]
    failures = sum(compare_target(t, args.baseline, args.show) for t in targets)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
