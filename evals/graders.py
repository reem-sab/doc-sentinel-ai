"""
Graders for agent eval cases.

A grader turns one finished run into a list of named checks. A case passes
when every check from every selected grader passes.

    class Grader:
        name = "..."
        def grade(self, case, run) -> list[Check]

Only the deterministic grader exists today. To add an LLM judge later,
write a class with the same interface and register it in GRADERS; it then
becomes available as `run_evals.py --grader llm_judge`.
"""

import re
from dataclasses import dataclass


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class RunArtifacts:
    """What a grader can look at after a case has run."""
    repo: str               # target repository after the run (working tree holds the edits)
    summary: dict           # the run's summary.json
    changed_files: list     # files changed in the working tree, relative to the repo
    pr_body: str | None     # the PR body the agent prepared, if any
    read: object            # read(path) -> text of a file in the repo, or None if it does not exist


class DeterministicGrader:
    """Exact checks from the case's `expect` block. Same run, same verdict."""

    name = "deterministic"

    def grade(self, case, run):
        expect = case["expect"]
        checks = []
        outcome = run.summary.get("outcome")
        wanted = expect.get("outcome", "dry_run_ready")
        wanted = wanted if isinstance(wanted, list) else [wanted]
        checks.append(Check("outcome", outcome in wanted,
                            "got " + str(outcome) + ", expected " + " or ".join(wanted)
                            + (" (" + run.summary["message"] + ")" if run.summary.get("message") else "")))

        must_change = expect.get("must_change", [])
        allowed = set(must_change) | set(expect.get("may_change", []))
        for path in must_change:
            checks.append(Check("changed: " + path, path in run.changed_files,
                                "" if path in run.changed_files else "the agent did not change it"))
        unexpected = [p for p in run.changed_files if p not in allowed]
        checks.append(Check("no other files changed", not unexpected,
                            "unexpected changes: " + ", ".join(unexpected) if unexpected else ""))

        for path, rules in expect.get("docs", {}).items():
            text = run.read(path)
            if text is None:
                checks.append(Check("exists: " + path, False, "file is missing after the run"))
                continue
            for s in rules.get("must_contain", []):
                checks.append(Check(path + " contains " + repr(s), s in text))
            for s in rules.get("must_not_contain", []):
                checks.append(Check(path + " does not contain " + repr(s), s not in text))
            for pattern in rules.get("must_match", []):
                checks.append(Check(path + " matches /" + pattern + "/", re.search(pattern, text) is not None))
            for pattern in rules.get("must_not_match", []):
                m = re.search(pattern, text)
                checks.append(Check(path + " does not match /" + pattern + "/", m is None,
                                    "found " + repr(m.group(0)) if m else ""))

        # Every changed doc must have passed its latest drift check on exactly its final content.
        docs_state = run.summary.get("docs", {})
        for path in run.changed_files:
            info = docs_state.get(path)
            ok = bool(info) and info.get("latest_status") == "pass"
            detail = "never checked" if not info else "latest check: " + str(info.get("latest_status"))
            checks.append(Check("drift check passed: " + path, ok, "" if ok else detail))

        # Every MINOR item must appear in the PR body, under the MINOR heading.
        minor = run.summary.get("minor_items", [])
        if run.pr_body is not None:
            section = run.pr_body.split("## MINOR drift for the reviewer", 1)
            checks.append(Check("PR body has the MINOR heading", len(section) == 2))
            for item in minor:
                listed = len(section) == 2 and ("`" + item["doc_path"] + "`") in section[1].split("\n## ", 1)[0]
                checks.append(Check("MINOR item listed: " + item["doc_path"], listed))
        return checks


GRADERS = {
    DeterministicGrader.name: DeterministicGrader,
}
