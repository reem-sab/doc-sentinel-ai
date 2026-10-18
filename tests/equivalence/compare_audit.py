"""
Check that the refactored src/audit.py behaves exactly like the original.

Runs every scenario twice, once with audit.py from a baseline commit and once
with the working-tree audit.py, and compares everything each run produced.

Usage:
    python tests/equivalence/compare_audit.py [--baseline COMMIT] [--show SCENARIO]

    --baseline  Commit holding the original audit.py (default: b3d3c84, the
                last commit before drift_core.py was extracted).
    --show      Print the PR or issue comment a scenario posted.
"""

import os
import sys
import json
import argparse
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
from scenarios import SCENARIOS  # noqa: E402

DEFAULT_BASELINE = "b3d3c84"
HASH_SEEDS = ["0", "4242"]   # set order decides doc order; check more than one


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
        return json.load(f)


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
    return {
        "exit": result["exit_code"],
        "label": label or "-",
        "gemini_calls": len(result["gemini_calls"]),
        "comments": len(result["comments"]),
        "events": ",".join(events),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--show", default=None)
    args = parser.parse_args()

    files = baseline_tree(args.baseline)
    failures = 0

    with tempfile.TemporaryDirectory() as tmp:
        baseline_audit = os.path.join(tmp, "baseline", "audit.py")
        os.makedirs(os.path.dirname(baseline_audit))
        with open(baseline_audit, "wb") as f:
            f.write(git("show", args.baseline + ":src/audit.py"))
        current_audit = os.path.join(REPO_ROOT, "src", "audit.py")

        print("Baseline: " + args.baseline + ":src/audit.py   Current: working tree src/audit.py")
        print("Compared per run: stdout, exit code, PR/issue comments, GITHUB_OUTPUT, telemetry,")
        print("every prompt sent to the model (+ model name, API key), sleeps, GitHub refs read.\n")
        header = "{:<26} {:<9} {:<5} {:<22} {:>5} {:>8}  {}".format(
            "scenario", "result", "exit", "label", "calls", "comments", "telemetry")
        print(header)
        print("-" * len(header))

        for name, sc in SCENARIOS.items():
            scenario = dict(sc, files=files)
            verdicts = []
            for seed in HASH_SEEDS:
                old = run_once(baseline_audit, scenario, seed, tmp)
                new = run_once(current_audit, scenario, seed, tmp)
                verdicts.append(first_difference(old, new))
            diff = next((d for d in verdicts if d), None)
            failures += bool(diff)
            s = summarize(new)
            print("{:<26} {:<9} {:<5} {:<22} {:>5} {:>8}  {}".format(
                name, "IDENTICAL" if not diff else "DIFFERENT", str(s["exit"]), s["label"],
                s["gemini_calls"], s["comments"], s["events"]))
            if diff:
                print("    first difference: " + diff)
            if args.show == name:
                for c in new["comments"]:
                    print("\n--- comment posted on " + c["on"] + " ---\n" + c["body"] + "\n--- end ---\n")

    print("\n" + str(len(SCENARIOS) - failures) + "/" + str(len(SCENARIOS))
          + " scenarios identical (each run with PYTHONHASHSEED " + " and ".join(HASH_SEEDS) + ")")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
