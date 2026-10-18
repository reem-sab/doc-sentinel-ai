"""
A local stand-in for the Anthropic Messages API that plays back a scripted
conversation, so the real agent (Claude Agent SDK + Claude Code CLI + hooks +
MCP servers) can be tested end to end without a model or an API key.

The script is a list of assistant turns. Turn N answers the request that
already holds N assistant messages. Each turn is a list of blocks:

    {"text": "..."}                         a text block
    {"tool": "Read", "input": {...}}        a tool call

Strings in tool inputs may use "{repo}" for the target repository path. A
request without the agent's tools (the CLI's own side requests) gets a short
text reply. Every main-loop request is recorded, so tests can check what the
agent sent back (tool results, denials).
"""

import json
import uuid
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

AGENT_TOOL_MARKER = "mcp__repo__git_diff"


class ScriptedModel:
    def __init__(self, turns, repo):
        self.turns = turns
        self.repo = repo
        self.requests = []          # main-loop request bodies, in order
        self.side_requests = 0
        self.lock = threading.Lock()

    def _fill(self, value):
        if isinstance(value, str):
            return value.replace("{repo}", self.repo)
        if isinstance(value, dict):
            return {k: self._fill(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._fill(v) for v in value]
        return value

    def reply_blocks(self, body):
        tool_names = [t.get("name") for t in body.get("tools", [])]
        if AGENT_TOOL_MARKER not in tool_names:
            with self.lock:
                self.side_requests += 1
            return [{"type": "text", "text": "ok"}]
        with self.lock:
            self.requests.append(body)
        n = sum(1 for m in body.get("messages", []) if m.get("role") == "assistant")
        turn = self.turns[n] if n < len(self.turns) else [{"text": "Script finished."}]
        blocks = []
        for i, b in enumerate(turn):
            if "tool" in b:
                blocks.append({"type": "tool_use", "id": "toolu_%02d_%02d" % (n, i),
                               "name": b["tool"], "input": self._fill(b["input"])})
            else:
                blocks.append({"type": "text", "text": self._fill(b["text"])})
        return blocks

    def tool_results(self):
        """Every tool_result the agent sent back, in order: (tool name, is_error, text)."""
        names, results = {}, []
        for body in self.requests:
            for m in body.get("messages", []):
                content = m.get("content")
                if not isinstance(content, list):
                    continue
                for c in content:
                    if c.get("type") == "tool_use":
                        names[c["id"]] = c["name"]
        seen = set()
        for body in self.requests:
            for m in body.get("messages", []):
                content = m.get("content")
                if m.get("role") != "user" or not isinstance(content, list):
                    continue
                for c in content:
                    if c.get("type") == "tool_result" and c["tool_use_id"] not in seen:
                        seen.add(c["tool_use_id"])
                        text = c.get("content")
                        if isinstance(text, list):
                            text = "".join(x.get("text", "") for x in text if isinstance(x, dict))
                        results.append((names.get(c["tool_use_id"]), bool(c.get("is_error")), text or ""))
        return results


def _sse(handler, event, data):
    handler.wfile.write(("event: " + event + "\ndata: " + json.dumps(data) + "\n\n").encode())


class _Handler(BaseHTTPRequestHandler):
    model = None  # set per server

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length)
        if self.headers.get("content-encoding") == "gzip":
            import gzip
            raw = gzip.decompress(raw)
        if not self.path.startswith("/v1/messages") or "count_tokens" in self.path:
            body = json.dumps({"input_tokens": 100}).encode() if "count_tokens" in self.path else b"{}"
            self.send_response(200 if "count_tokens" in self.path else 404)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return

        req = json.loads(raw or b"{}")
        blocks = self.model.reply_blocks(req)
        stop = "tool_use" if any(b["type"] == "tool_use" for b in blocks) else "end_turn"
        usage = {"input_tokens": 100, "output_tokens": 20, "cache_creation_input_tokens": 0,
                 "cache_read_input_tokens": 0}
        # A unique id per response: the CLI merges assistant messages that share one.
        message = {"id": "msg_fake_" + uuid.uuid4().hex[:12], "type": "message", "role": "assistant", "model": req.get("model", "fake"),
                   "content": [], "stop_reason": None, "stop_sequence": None, "usage": usage}

        if not req.get("stream"):
            message.update(content=blocks, stop_reason=stop)
            out = json.dumps(message).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
            return

        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.end_headers()
        _sse(self, "message_start", {"type": "message_start", "message": message})
        for i, b in enumerate(blocks):
            if b["type"] == "text":
                _sse(self, "content_block_start", {"type": "content_block_start", "index": i,
                                                   "content_block": {"type": "text", "text": ""}})
                _sse(self, "content_block_delta", {"type": "content_block_delta", "index": i,
                                                   "delta": {"type": "text_delta", "text": b["text"]}})
            else:
                _sse(self, "content_block_start", {"type": "content_block_start", "index": i,
                                                   "content_block": {"type": "tool_use", "id": b["id"],
                                                                     "name": b["name"], "input": {}}})
                _sse(self, "content_block_delta", {"type": "content_block_delta", "index": i,
                                                   "delta": {"type": "input_json_delta",
                                                             "partial_json": json.dumps(b["input"])}})
            _sse(self, "content_block_stop", {"type": "content_block_stop", "index": i})
        _sse(self, "message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                                     "usage": {"output_tokens": 20}})
        _sse(self, "message_stop", {"type": "message_stop"})
        self.wfile.flush()


def start(turns, repo):
    """Start the fake API on a free local port. Returns (server, model, base_url)."""
    model = ScriptedModel(turns, repo)
    handler = type("Handler", (_Handler,), {"model": model})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, model, "http://127.0.0.1:" + str(server.server_address[1])
