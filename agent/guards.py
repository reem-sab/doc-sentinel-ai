"""
Hooks that log every tool call and enforce the run's rules in code, not just
in the prompt.

PreToolUse   Logs the call. Denies it when:
               - a file tool reaches outside the target repository,
               - a write targets anything but a doc file (.md, .mdx, .rst) or .git/,
               - the PR is already open or the run was stopped,
               - the tool is not on the run's allowlist.
PostToolUse  Logs the result. When check_drift reports limit_reached, stops the
             session so the runner can write the failure report.
PostToolUseFailure  Logs the error.
"""

import json

from claude_agent_sdk import HookMatcher

DRIFT_SERVER = "drift"
REPO_SERVER = "repo"

BUILTIN_TOOLS = ["Read", "Grep", "Glob", "Edit", "Write"]
MCP_TOOLS = [
    "mcp__" + DRIFT_SERVER + "__find_candidate_docs",
    "mcp__" + DRIFT_SERVER + "__readability_score",
    "mcp__" + DRIFT_SERVER + "__check_drift",
    "mcp__" + DRIFT_SERVER + "__drift_check_status",
    "mcp__" + REPO_SERVER + "__git_diff",
    "mcp__" + REPO_SERVER + "__open_draft_pr",
]
ALLOWED_TOOLS = BUILTIN_TOOLS + MCP_TOOLS
WRITE_TOOLS = {"Edit", "Write"}
CHECK_DRIFT = "mcp__" + DRIFT_SERVER + "__check_drift"


def _deny(reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def tool_response_data(response):
    """
    Pull a JSON result out of a tool response, whatever shape it arrives in:
    a dict (possibly with structuredContent), a list of content blocks, or a string.
    """
    if isinstance(response, dict):
        for key in ("structuredContent", "structured_content"):
            if isinstance(response.get(key), dict):
                return response[key]
        if "content" in response:
            return tool_response_data(response["content"])
        return response
    if isinstance(response, list):
        for block in response:
            text = block.get("text") if isinstance(block, dict) else None
            if text:
                data = tool_response_data(text)
                if isinstance(data, dict):
                    return data
        return None
    if isinstance(response, str):
        try:
            data = json.loads(response)
            return data if isinstance(data, dict) else None
        except ValueError:
            return None
    return None


def check_tool_call(ctx, tool_name, tool_input):
    """The reason to deny a tool call, or None to allow it."""
    if ctx.stopped:
        return "The run has stopped (" + (ctx.stop_reason or "stopped") + "). No more tool calls."
    if tool_name not in ALLOWED_TOOLS:
        return tool_name + " is not available in this run."

    if tool_name in ("Read", "Edit", "Write"):
        path = tool_input.get("file_path") or ""
        full = ctx.resolve_in_repo(path) if path else None
        if full is None:
            return "Path is outside the target repository: " + str(path)
        if tool_name in WRITE_TOOLS:
            rel = full[len(ctx.repo_root) + 1:]
            if rel.split("/")[0] == ".git":
                return "Writing inside .git is not allowed."
            if not ctx.is_doc_path(rel):
                return "Only documentation files (.md, .mdx, .rst) can be written. " + rel + " is not one."
            if ctx.pr_url or ctx.dry_run_pr:
                return "The PR is already prepared; the docs can no longer change in this run."
    elif tool_name in ("Grep", "Glob"):
        path = tool_input.get("path")
        if path and ctx.resolve_in_repo(path) is None:
            return "Path is outside the target repository: " + str(path)
        pattern = tool_input.get("pattern") or ""
        if tool_name == "Glob" and (pattern.startswith(("/", "~")) or ".." in pattern.split("/")):
            static = pattern.split("*")[0].rsplit("/", 1)[0] or "/"
            if pattern.startswith("~") or ".." in pattern.split("/") or ctx.resolve_in_repo(static) is None:
                return "Glob pattern reaches outside the target repository: " + pattern
    return None


def build_hooks(ctx):
    log = ctx.log

    async def pre_tool_use(hook_input, tool_use_id, context):
        name = hook_input["tool_name"]
        tool_input = hook_input.get("tool_input", {})
        log.add("tool_call", tool=name, tool_use_id=tool_use_id, input=tool_input)
        reason = check_tool_call(ctx, name, tool_input)
        if reason:
            log.add("tool_denied", tool=name, tool_use_id=tool_use_id, reason=reason)
            return _deny(reason)
        return {}

    async def post_tool_use(hook_input, tool_use_id, context):
        name = hook_input["tool_name"]
        response = hook_input.get("tool_response")
        log.add("tool_result", tool=name, tool_use_id=tool_use_id, duration_ms=hook_input.get("duration_ms"),
                result=response)
        if name != CHECK_DRIFT:
            return {}

        data = tool_response_data(response) or {}
        if "status" not in data:
            return {}
        log.add("drift_check", doc_path=data.get("doc_path"), status=data.get("status"),
                severity=data.get("severity"), explanation=data.get("explanation") or data.get("reason"),
                attempt=data.get("attempt"), failed_attempts=data.get("failed_attempts"),
                max_attempts=data.get("max_attempts"))
        if data.get("limit_reached"):
            ctx.stopped = True
            ctx.stop_reason = ("Drift check still fails for " + str(data.get("doc_path")) + " after "
                               + str(data.get("failed_attempts")) + " attempts")
            log.add("guard_stop", reason=ctx.stop_reason + ". Stopping the run and reporting.")
            return {"continue_": False, "stopReason": ctx.stop_reason}
        return {}

    async def post_tool_use_failure(hook_input, tool_use_id, context):
        log.add("tool_error", tool=hook_input["tool_name"], tool_use_id=tool_use_id,
                error=hook_input.get("error"), duration_ms=hook_input.get("duration_ms"))
        return {}

    return {
        "PreToolUse": [HookMatcher(matcher=None, hooks=[pre_tool_use])],
        "PostToolUse": [HookMatcher(matcher=None, hooks=[post_tool_use])],
        "PostToolUseFailure": [HookMatcher(matcher=None, hooks=[post_tool_use_failure])],
    }
