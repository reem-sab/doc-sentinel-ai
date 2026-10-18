"""
Run the agent against every eval case and report the pass rate.

Usage:
    python evals/run_evals.py [--case NAME ...] [--jobs N] [--model MODEL] [--effort LEVEL]
        [--grader deterministic] [--min-pass-rate 0.8] [--out DIR]

Each case builds a small repo, applies a code change, runs the agent in
dry-run mode (no push, no PR), and grades the result. Results go to
evals/results/<timestamp>/: results.json, report.md, and each case's repo and
full run log.

Every case is a real agent run (Claude) plus drift checks (Gemini), so it
needs ANTHROPIC_API_KEY and GOOGLE_API_KEY and costs money; the report shows
what each case cost.

Exit code: 0, or 1 when --min-pass-rate is given and the pass rate is below it.
"""

import os
import sys
import json
import asyncio
import argparse
from dataclasses import asdict
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

from agent.runner import DEFAULT_EFFORT, DEFAULT_MODEL  # noqa: E402
from evals.graders import GRADERS  # noqa: E402
from evals.harness import load_cases, run_cases  # noqa: E402


def write_report(results, out_dir, settings):
    passed = sum(r.passed for r in results)
    rate = passed / len(results) if results else 0.0
    costs = [r.cost_usd for r in results if r.cost_usd is not None]
    data = {"pass_rate": rate, "passed": passed, "total": len(results), "settings": settings,
            "total_cost_usd": sum(costs) if costs else None, "cases": [asdict(r) for r in results]}
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=lambda o: asdict(o) if hasattr(o, "__dataclass_fields__") else str(o))

    lines = ["# Doc-Sentinel agent evals", "",
             "**Pass rate: " + str(passed) + "/" + str(len(results)) + " (" + format(rate, ".0%") + ")**", "",
             "Model `" + settings["model"] + "`, effort `" + settings["effort"] + "`, graders: "
             + ", ".join(settings["graders"]) + ". Started " + settings["started"] + ".", "",
             "| Case | Result | Outcome | Checks | Turns | Cost | Time |", "| :--- | :--- | :--- | ---: | ---: | ---: | ---: |"]
    for r in results:
        ok = sum(c.passed for c in r.checks)
        lines.append("| `" + r.name + "` | " + ("✅ pass" if r.passed else "❌ fail") + " | " + str(r.outcome or "-")
                     + " | " + str(ok) + "/" + str(len(r.checks)) + " | " + str(r.num_turns or "-") + " | "
                     + ("$%.3f" % r.cost_usd if r.cost_usd is not None else "-") + " | " + str(r.duration_s) + "s |")
    if costs:
        lines += ["", "Total cost: $%.3f" % sum(costs)]
    for r in results:
        failed = [c for c in r.checks if not c.passed]
        if r.passed and not r.error:
            continue
        lines += ["", "## `" + r.name + "`", "", r.description, ""]
        if r.error:
            lines.append("- **Error:** " + r.error)
        lines += ["- ❌ " + c.name + (": " + c.detail if c.detail else "") for c in failed]
        if r.run_dir:
            lines.append("- Run log: `" + os.path.relpath(os.path.join(r.run_dir, "report.md"), out_dir) + "`")
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return rate


def main(argv=None):
    load_dotenv()
    parser = argparse.ArgumentParser(description="Run the Doc-Sentinel agent evals.")
    parser.add_argument("--case", action="append", dest="cases", help="Run only this case (repeatable).")
    parser.add_argument("--jobs", type=int, default=1, help="Cases to run at once (default 1).")
    parser.add_argument("--model", default=os.environ.get("DOC_SENTINEL_AGENT_MODEL") or DEFAULT_MODEL)
    parser.add_argument("--effort", default=DEFAULT_EFFORT, choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--max-turns", type=int, default=60)
    parser.add_argument("--grader", action="append", dest="graders", choices=sorted(GRADERS),
                        help="Grader to apply (repeatable). Default: deterministic.")
    parser.add_argument("--min-pass-rate", type=float, default=None)
    parser.add_argument("--out", default=None, help="Results folder (default: evals/results/<timestamp>).")
    args = parser.parse_args(argv)

    cases = load_cases(only=args.cases)
    if not cases:
        print("No cases found.")
        return 1
    missing = [k for k in ("GOOGLE_API_KEY",) if not os.environ.get(k)]
    if missing:
        print("Missing " + ", ".join(missing) + ". The drift check needs it.")
        return 1
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print("Note: ANTHROPIC_API_KEY is not set; the agent will use the Claude Code CLI's own login, if any.")

    started = datetime.now(timezone.utc)
    out_dir = args.out or os.path.join(ROOT, "evals", "results", started.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(out_dir, exist_ok=True)
    graders = args.graders or ["deterministic"]
    settings = {"model": args.model, "effort": args.effort, "max_turns": args.max_turns, "graders": graders,
                "started": started.isoformat(timespec="seconds")}
    print("Running " + str(len(cases)) + " case(s) with " + args.model + " -> " + out_dir)

    def progress(r):
        ok = sum(c.passed for c in r.checks)
        print(("  PASS " if r.passed else "  FAIL ") + r.name + "  (" + str(r.outcome) + ", "
              + str(ok) + "/" + str(len(r.checks)) + " checks, " + str(r.duration_s) + "s"
              + (", $%.3f" % r.cost_usd if r.cost_usd is not None else "") + ")"
              + ("  error: " + r.error if r.error else ""))
        for c in r.checks:
            if not c.passed:
                print("       - " + c.name + (": " + c.detail if c.detail else ""))

    results = asyncio.run(run_cases(cases, out_dir, jobs=args.jobs, graders=graders, progress=progress,
                                    model=args.model, effort=args.effort, max_turns=args.max_turns))
    rate = write_report(results, out_dir, settings)
    print("\nPass rate: " + str(sum(r.passed for r in results)) + "/" + str(len(results)) + " (" + format(rate, ".0%") + ")")
    print("Report: " + os.path.join(out_dir, "report.md"))
    if args.min_pass_rate is not None and rate < args.min_pass_rate:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
