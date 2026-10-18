"""
Run log for the remediation agent.

Every run gets its own folder (runs/<run-id>/ by default) with:

    events.jsonl   One JSON object per event, in order. The full record.
    report.md      The same events as a readable timeline, for demos and review.
    summary.json   Outcome, PR link, per-doc verdicts, cost. Read by the evals.

Event types:
    run_started    Configuration of the run (no secrets).
    decision       Text the agent wrote between actions: what it decided and why.
    reasoning      Summarized thinking, when the model returns it.
    tool_call      A tool the agent asked to run, with its input.
    tool_denied    A guard refused a tool call, with the reason.
    tool_result    What the tool returned (shortened in report.md).
    tool_error     A tool that failed.
    drift_check    A drift check verdict, pulled out of its tool_result.
    guard_stop     A guard ended the session (for example, the attempt limit).
    run_finished   Final outcome, cost, and turn count.
"""

import os
import json
import threading
from datetime import datetime, timezone

# Longest string kept per field in events.jsonl. Longer values are cut, with a note.
MAX_FIELD_CHARS = 20_000
# Longest tool input or result shown in report.md.
REPORT_PREVIEW_CHARS = 600


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _clip(value, limit):
    """Shorten long strings anywhere in a JSON-like value, saying how much was cut."""
    if isinstance(value, str):
        if len(value) <= limit:
            return value
        return value[:limit] + "\n... [" + str(len(value) - limit) + " more characters]"
    if isinstance(value, dict):
        return {k: _clip(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_clip(v, limit) for v in value]
    return value


def _preview(value, limit=REPORT_PREVIEW_CHARS):
    text = value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False, default=str)
    return _clip(text, limit)


def short_tool_name(name):
    """mcp__drift__check_drift -> drift.check_drift; built-in names stay as they are."""
    if name.startswith("mcp__"):
        parts = name.split("__", 2)
        if len(parts) == 3:
            return parts[1] + "." + parts[2]
    return name


class RunLog:
    """Append-only event log, written to disk as each event arrives."""

    def __init__(self, run_dir, echo=True):
        self.run_dir = run_dir
        self.echo = echo
        os.makedirs(run_dir, exist_ok=True)
        self.events_path = os.path.join(run_dir, "events.jsonl")
        self.report_path = os.path.join(run_dir, "report.md")
        self.summary_path = os.path.join(run_dir, "summary.json")
        self.events = []
        self.lock = threading.Lock()
        open(self.events_path, "w").close()

    def add(self, event_type, **fields):
        event = {"seq": len(self.events) + 1, "ts": _now(), "type": event_type}
        event.update(_clip(fields, MAX_FIELD_CHARS))
        with self.lock:
            self.events.append(event)
            with open(self.events_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        if self.echo:
            line = self._console_line(event)
            if line:
                print(line, flush=True)
        return event

    # --- Console ----------------------------------------------------------------

    def _console_line(self, e):
        t = e["type"]
        if t == "run_started":
            return "▶ run " + e.get("run_id", "") + " on " + e.get("repo", "") + " range " + e.get("diff_range", "")
        if t == "decision":
            return "  💬 " + e["text"].strip().replace("\n", "\n     ")
        if t == "tool_call":
            return "  🔧 " + short_tool_name(e["tool"]) + " " + _preview(e.get("input", {}), 160).replace("\n", " ")
        if t == "tool_denied":
            return "  ⛔ denied " + short_tool_name(e["tool"]) + ": " + e["reason"]
        if t == "tool_error":
            return "  ❌ " + short_tool_name(e["tool"]) + " failed: " + _preview(e.get("error", ""), 200)
        if t == "drift_check":
            return ("  🛡️  drift check " + e["doc_path"] + ": " + str(e["status"]).upper()
                    + (" (" + str(e["severity"]) + ")" if e.get("severity") else "")
                    + " — attempt " + str(e.get("attempt", "?")) + ", failed " + str(e.get("failed_attempts", "?"))
                    + "/" + str(e.get("max_attempts", "?")))
        if t == "guard_stop":
            return "  🛑 " + e["reason"]
        if t == "run_finished":
            return "■ " + e["outcome"] + (": " + e["message"] if e.get("message") else "")
        return None

    # --- Files ------------------------------------------------------------------

    def write_summary(self, summary):
        with open(self.summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False, default=str)

    def write_report(self, summary):
        """Render report.md: outcome first, then every step in order."""
        lines = ["# Doc-Sentinel agent run `" + summary.get("run_id", "") + "`", ""]
        lines += [
            "| | |", "| :--- | :--- |",
            "| **Outcome** | " + summary.get("outcome", "") + " |",
            "| **Repository** | `" + str(summary.get("repo", "")) + "` |",
            "| **Code changes** | " + str(summary.get("source", "")) + " |",
            "| **Pull request** | " + (summary.get("pr_url") or "none") + " |",
            "| **Agent model** | " + str(summary.get("model", "")) + " |",
            "| **Drift checker** | " + str(summary.get("checker", "")) + " |",
            "| **Turns / cost** | " + str(summary.get("num_turns", "?")) + " / "
            + ("$%.4f" % summary["cost_usd"] if summary.get("cost_usd") is not None else "?") + " |",
            "",
        ]
        if summary.get("message"):
            lines += ["> " + summary["message"].replace("\n", "\n> "), ""]

        docs = summary.get("docs", {})
        if docs:
            lines += ["## Drift check results", "", "| Doc | Final verdict | Checks | Failed |", "| :--- | :--- | ---: | ---: |"]
            for path, d in docs.items():
                verdict = d["latest_status"].upper() + (" (" + d["latest_severity"] + ")" if d.get("latest_severity") else "")
                lines.append("| `" + path + "` | " + verdict + " | " + str(d["checks_run"]) + " | " + str(d["failed_attempts"]) + " |")
            lines.append("")

        lines += ["## Timeline", ""]
        step = 0
        for e in self.events:
            t = e["type"]
            if t == "decision":
                lines += ["**Decision:** " + e["text"].strip(), ""]
            elif t == "reasoning":
                lines += ["<details><summary>Reasoning summary</summary>", "", e["text"].strip(), "", "</details>", ""]
            elif t == "tool_call":
                step += 1
                lines += ["### " + str(step) + ". `" + short_tool_name(e["tool"]) + "`  <sub>" + e["ts"] + "</sub>", "",
                          "```json", _preview(e.get("input", {})), "```", ""]
            elif t == "tool_result":
                dur = " (" + str(e["duration_ms"]) + " ms)" if e.get("duration_ms") is not None else ""
                lines += ["<details><summary>Result" + dur + "</summary>", "", "```", _preview(e.get("result", "")), "```",
                          "", "</details>", ""]
            elif t == "drift_check":
                lines += ["> 🛡️ **Drift check** `" + e["doc_path"] + "`: **" + str(e["status"]).upper() + "**"
                          + (" (" + e["severity"] + ")" if e.get("severity") else "")
                          + ", failed attempts " + str(e.get("failed_attempts")) + "/" + str(e.get("max_attempts"))
                          + ("  \n> " + e["explanation"] if e.get("explanation") else ""), ""]
            elif t == "tool_denied":
                lines += ["> ⛔ **Denied** `" + short_tool_name(e["tool"]) + "`: " + e["reason"], ""]
            elif t == "tool_error":
                lines += ["> ❌ **Tool error** `" + short_tool_name(e["tool"]) + "`: " + _preview(e.get("error", ""), 400), ""]
            elif t == "guard_stop":
                lines += ["> 🛑 **Stopped:** " + e["reason"], ""]

        if summary.get("failure_report"):
            lines += ["## Failure report", "", summary["failure_report"], ""]
        if summary.get("agent_final_message"):
            lines += ["## Agent's final message", "", summary["agent_final_message"].strip(), ""]

        with open(self.report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
