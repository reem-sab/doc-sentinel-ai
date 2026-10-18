"""
Start the real drift check MCP server with a scripted checker instead of Gemini.

DOC_SENTINEL_SCRIPTED_REPLIES points to a JSON object mapping a doc path to a
list of replies. Each check of that doc returns the next reply; the last one
repeats. Every prompt received is appended to DOC_SENTINEL_SCRIPTED_PROMPTS.
"""

import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src import drift_core  # noqa: E402
from mcp_servers import drift_check_server  # noqa: E402

replies = json.load(open(os.environ["DOC_SENTINEL_SCRIPTED_REPLIES"], encoding="utf-8"))
calls = {}


def scripted(prompt, model, log):
    with open(os.environ["DOC_SENTINEL_SCRIPTED_PROMPTS"], "a", encoding="utf-8") as f:
        f.write(json.dumps({"model": model, "prompt": prompt}) + "\n")
    for doc_path, doc_replies in replies.items():
        if "EXISTING DOCS (" + doc_path + "):" in prompt:
            n = calls.get(doc_path, 0)
            calls[doc_path] = n + 1
            return doc_replies[min(n, len(doc_replies) - 1)]
    raise RuntimeError("no scripted reply for this prompt")


drift_core.PROVIDERS["scripted"] = scripted
os.environ["DOC_SENTINEL_CHECKER_PROVIDER"] = "scripted"
drift_check_server.main()
