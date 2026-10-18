"""
Doc-Sentinel Drift Check MCP Server
-----------------------------------
Exposes the drift check (src/drift_core.py) as MCP tools over stdio, so an
agent calls it as a tool instead of importing it.

Tools:
    find_candidate_docs  Docs whose names match the changed files (the Action's mapping).
    readability_score    The AI-readability score of one doc.
    check_drift          Run the drift check on one doc in the working tree.
    drift_check_status   Latest verdict for every doc checked in this session.

Each doc gets a limited number of failed checks (default 3). After the last
one, check_drift refuses that doc and reports limit_reached, so the caller
has to stop and report instead of retrying forever.

Usage:
    python mcp_servers/drift_check_server.py --repo PATH [--range BASE..HEAD]
        [--max-attempts 3] [--state-file PATH]

    --repo          Local checkout to check. Default: DOC_SENTINEL_REPO or the current directory.
    --range         Pin the commit range every check uses. Default: DOC_SENTINEL_DIFF_RANGE.
                    When pinned, callers cannot check against a different range.
    --max-attempts  Failed checks allowed per doc. Default: DOC_SENTINEL_MAX_ATTEMPTS or 3.
    --state-file    Write every verdict to this JSON file after each check.

The checker model comes from DOC_SENTINEL_CHECKER_PROVIDER and
DOC_SENTINEL_CHECKER_MODEL (see src/drift_core.py). Stdout carries the MCP
protocol, so all logging goes to stderr.
"""

import os
import sys
import json
import argparse
import functools
import threading
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src import drift_core  # noqa: E402

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

DEFAULT_MAX_ATTEMPTS = 3


def log(message):
    print("[drift-check] " + message, file=sys.stderr, flush=True)


class DriftCheckState:
    """Per-session record of every check, used for the attempt limit and the status tool."""

    def __init__(self, repo_root, pinned_range, max_attempts, state_file):
        self.repo_root = os.path.realpath(repo_root)
        self.pinned_range = pinned_range
        self.max_attempts = max_attempts
        self.state_file = state_file
        self.checks = {}   # doc_path -> list of check results, oldest first
        self.lock = threading.Lock()

    def resolve_range(self, diff_range):
        if self.pinned_range:
            if diff_range and diff_range != self.pinned_range:
                raise ValueError(
                    "This server is pinned to the range " + self.pinned_range
                    + "; got " + diff_range + ". Omit diff_range to use the pinned range."
                )
            return self.pinned_range
        if not diff_range:
            raise ValueError("diff_range is required (for example BASE_SHA..HEAD_SHA).")
        return drift_core.validate_diff_range(diff_range)

    def normalize_doc(self, doc_path):
        full = drift_core.resolve_doc_path(self.repo_root, doc_path)
        return os.path.relpath(full, self.repo_root).replace(os.sep, "/")

    def failed_count(self, doc_path):
        return sum(1 for c in self.checks.get(doc_path, []) if c["status"] == "fail")

    def record(self, doc_path, result):
        with self.lock:
            self.checks.setdefault(doc_path, []).append(result)
            self.save()

    def summary(self):
        docs = {}
        for doc_path, checks in sorted(self.checks.items()):
            latest = checks[-1]
            docs[doc_path] = {
                "latest_status": latest["status"],
                "latest_severity": latest["severity"],
                "latest_explanation": latest["explanation"],
                "latest_doc_sha256": latest["doc_sha256"],
                "checks_run": len(checks),
                "failed_attempts": self.failed_count(doc_path),
                "limit_reached": self.failed_count(doc_path) >= self.max_attempts,
            }
        minor_items = [
            {"doc_path": d, "explanation": c[-1]["explanation"]}
            for d, c in sorted(self.checks.items())
            if c[-1]["status"] == "pass" and c[-1]["severity"] == "minor"
        ]
        return {
            "repo": self.repo_root,
            "pinned_range": self.pinned_range,
            "max_attempts": self.max_attempts,
            "all_passing": bool(docs) and all(d["latest_status"] == "pass" for d in docs.values()),
            "docs": docs,
            "minor_items": minor_items,
        }

    def save(self):
        if not self.state_file:
            return
        data = self.summary()
        data["checks"] = self.checks
        tmp = self.state_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.state_file)


def _report_errors(fn):
    """
    Turn failures into ToolError so the caller sees the message.

    MCP hides the text of any other exception from the client, but the agent
    needs it (bad path, wrong range, missing key, checker outage) to decide
    what to do next.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except (ValueError, OSError, RuntimeError) as e:
            raise ToolError(str(e)) from e
        except Exception as e:
            log("checker error: " + type(e).__name__ + ": " + str(e))
            raise ToolError("Drift checker failed (" + type(e).__name__ + "): " + str(e)
                            + ". No attempt was counted.") from e
    return wrapper


def build_server(state):
    server = MCPServer(
        name="doc-sentinel-drift-check",
        instructions=(
            "Doc-Sentinel's drift check. check_drift compares one doc in the working tree "
            "against the code changes in a commit range and returns pass or fail. "
            "A doc passes with no drift or MINOR drift; MINOR items must be reported to the reviewer. "
            "Each doc allows " + str(state.max_attempts) + " failed checks, then it is locked."
        ),
    )

    @server.tool(structured_output=True)
    @_report_errors
    def find_candidate_docs(changed_files: list[str] | None = None, diff_range: str | None = None) -> dict[str, Any]:
        """
        List docs whose file names match the changed files, using the same
        name-based mapping as the GitHub Action. This is a starting point only:
        it misses docs that mention the code without sharing its name, so also
        search the repository for the changed functions and settings.

        Pass changed_files, or omit it to use the files changed in the commit range.
        """
        if changed_files is None:
            diff_range = state.resolve_range(diff_range)
            _, changed_files = drift_core.local_diff(state.repo_root, diff_range)
        md_files = drift_core.list_local_md_files(state.repo_root)
        by_file = drift_core.match_docs_by_file(md_files, changed_files)
        no_match = [f for f, docs in by_file.items() if not docs]
        return {
            "changed_files": changed_files,
            "matches": by_file,
            "no_name_match": no_match,
            "fallback_doc": drift_core.FALLBACK_DOC if no_match else None,
            "candidates": sorted(set(drift_core.match_docs(md_files, changed_files))),
            "all_docs": md_files,
        }

    @server.tool(structured_output=True)
    @_report_errors
    def readability_score(doc_path: str) -> dict[str, Any]:
        """AI-readability score (0-100) of one doc in the working tree, from the AI-Readability Style Guide rules."""
        doc_path = state.normalize_doc(doc_path)
        content = drift_core.read_local_doc(state.repo_root, doc_path)
        return {"doc_path": doc_path, "score": drift_core.DocSentinelIntelligence(content).calculate_score()}

    @server.tool(structured_output=True)
    @_report_errors
    def check_drift(doc_path: str, diff_range: str | None = None) -> dict[str, Any]:
        """
        Run Doc-Sentinel's drift check on one doc as it is now in the working
        tree, against the code changes in the commit range.

        status is "pass" (no drift, or MINOR drift) or "fail" (CRITICAL drift,
        or an answer that could not be read). On fail, use explanation and
        suggested_fix to revise the doc, then check again. MINOR drift passes,
        but list every MINOR item for the reviewer.

        Each doc allows a fixed number of failed checks. When limit_reached is
        true, stop editing that doc and report it.
        """
        doc_path = state.normalize_doc(doc_path)
        diff_range = state.resolve_range(diff_range)

        failed = state.failed_count(doc_path)
        if failed >= state.max_attempts:
            return {
                "doc_path": doc_path,
                "status": "limit_reached",
                "limit_reached": True,
                "failed_attempts": failed,
                "max_attempts": state.max_attempts,
                "reason": "This doc failed the drift check " + str(failed)
                          + " times. No more checks are allowed; stop and report it.",
            }

        settings = drift_core.checker_settings()
        if settings["provider"] == "gemini" and not (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")):
            raise ValueError("GOOGLE_API_KEY is not set. The gemini drift checker needs it; no attempt was counted.")

        log("check_drift " + doc_path + " against " + diff_range)
        result = drift_core.audit_local_doc(state.repo_root, diff_range, doc_path, log=log)
        result["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        state.record(doc_path, result)

        failed = state.failed_count(doc_path)
        result.update({
            "attempt": len(state.checks[doc_path]),
            "failed_attempts": failed,
            "max_attempts": state.max_attempts,
            "attempts_remaining": max(state.max_attempts - failed, 0),
            "limit_reached": failed >= state.max_attempts,
        })
        log(doc_path + ": " + result["status"] + " (" + result["reason"] + ")")
        return result

    @server.tool(structured_output=True)
    @_report_errors
    def drift_check_status() -> dict[str, Any]:
        """
        Latest drift verdict for every doc checked in this session, whether all
        of them pass, and the MINOR items that must go in the PR summary.
        """
        return state.summary()

    return server


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Doc-Sentinel drift check MCP server (stdio)")
    parser.add_argument("--repo", default=os.environ.get("DOC_SENTINEL_REPO") or os.getcwd())
    parser.add_argument("--range", dest="diff_range", default=os.environ.get("DOC_SENTINEL_DIFF_RANGE") or None)
    parser.add_argument("--max-attempts", type=int,
                        default=int(os.environ.get("DOC_SENTINEL_MAX_ATTEMPTS") or DEFAULT_MAX_ATTEMPTS))
    parser.add_argument("--state-file", default=os.environ.get("DOC_SENTINEL_STATE_FILE") or None)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.diff_range:
        drift_core.validate_diff_range(args.diff_range)
    if args.max_attempts < 1:
        raise SystemExit("--max-attempts must be at least 1")
    state = DriftCheckState(args.repo, args.diff_range, args.max_attempts, args.state_file)
    settings = drift_core.checker_settings()
    log("serving " + state.repo_root + " | range " + str(args.diff_range)
        + " | checker " + settings["provider"] + "/" + settings["model"]
        + " | max failed attempts per doc " + str(args.max_attempts))
    build_server(state).run("stdio")


if __name__ == "__main__":
    main()
