"""
Run one copy of audit.py (as the GitHub Action runs it) or historical_audit.py
(as the CLI runs it), with GitHub, Gemini, dotenv, and telemetry replaced by
recording fakes.

Usage (called by compare_audit.py, one subprocess per run):
    python run_audit_with_fakes.py AUDIT_PY SCENARIO_JSON OUTPUT_JSON

Everything the run produces is written to OUTPUT_JSON: stdout, exit code,
posted comments, GITHUB_OUTPUT lines, telemetry events, every prompt sent to
the model, every sleep, and the report file if the scenario's argv writes one
("{report}" in argv is replaced with a temp path).

Optional scenario keys: "argv" (command-line arguments), "env" (variables to
set; null unsets one).
"""

import io
import os
import sys
import json
import time
import types
import runpy
import tempfile
import contextlib

audit_path, scenario_path, output_path = sys.argv[1:4]
scenario = json.load(open(scenario_path, encoding="utf-8"))
record = {
    "comments": [], "telemetry": [], "gemini_calls": [], "sleeps": [],
}


# --- Fake GitHub --------------------------------------------------------------

class FakeContent:
    def __init__(self, path, kind, content=None):
        self.path = path
        self.type = kind
        self._content = content

    @property
    def decoded_content(self):
        return self._content.encode("utf-8")


class FakeRepo:
    def __init__(self, sc):
        self.full_name = sc.get("repo_name", "reem-sab/doc-sentinel-ai")
        self.files = sc["files"]                    # path -> content
        self.unreadable = set(sc.get("unreadable", []))
        self.scan_error = sc.get("scan_error")

    def get_contents(self, path, ref=None):
        record.setdefault("get_contents_refs", []).append(ref)
        if path == "" and self.scan_error:
            raise Exception(self.scan_error)
        if path in self.files:
            if path in self.unreadable:
                raise Exception("404 Not Found")
            return FakeContent(path, "file", self.files[path])
        prefix = path + "/" if path else ""
        children = {}
        for p in self.files:
            if p.startswith(prefix):
                head = p[len(prefix):].split("/")[0]
                full = prefix + head
                children[full] = "file" if full in self.files else "dir"
        if not children:
            raise Exception("404 Not Found")
        return [FakeContent(p, k, self.files.get(p)) for p, k in sorted(children.items())]

    def get_pull(self, number):
        pr = types.SimpleNamespace(
            base=types.SimpleNamespace(sha="base-sha"),
            head=types.SimpleNamespace(sha="head-sha"),
        )
        pr.create_issue_comment = lambda body: record["comments"].append(
            {"on": "pr#" + str(number), "body": body})
        return pr

    def compare(self, base, head):
        files = [types.SimpleNamespace(filename=f, patch=p) for f, p in scenario["pr_files"]]
        return types.SimpleNamespace(files=files)

    def get_issue(self, number):
        issue = types.SimpleNamespace(body=scenario["issue_body"])
        issue.create_comment = lambda body: record["comments"].append(
            {"on": "issue#" + str(number), "body": body})
        return issue


github_mod = types.ModuleType("github")
github_mod.Auth = types.SimpleNamespace(Token=lambda token: ("token", token))
github_mod.Github = lambda auth=None: types.SimpleNamespace(get_repo=lambda name: FakeRepo(scenario))
sys.modules["github"] = github_mod


# --- Fake Gemini --------------------------------------------------------------

error_counts = {}


def generate_content(model, contents):
    record["gemini_calls"].append({"model": model, "prompt": contents})
    for i, rule in enumerate(scenario["gemini"]):
        if rule["match"] in contents:
            errors = rule.get("errors", [])
            n = error_counts.get(i, 0)
            if n < len(errors):
                error_counts[i] = n + 1
                raise Exception(errors[n])
            return types.SimpleNamespace(text=rule["reply"])
    raise Exception("No scripted Gemini reply for this prompt")


def make_client(api_key=None):
    record.setdefault("gemini_api_keys", []).append(api_key)
    return types.SimpleNamespace(models=types.SimpleNamespace(generate_content=generate_content))


genai_mod = types.ModuleType("google.genai")
genai_mod.Client = make_client
google_mod = types.ModuleType("google")
google_mod.genai = genai_mod
sys.modules["google"] = google_mod
sys.modules["google.genai"] = genai_mod


# --- Fake dotenv, telemetry, sleep --------------------------------------------

dotenv_mod = types.ModuleType("dotenv")
dotenv_mod.load_dotenv = lambda *a, **k: None
sys.modules["dotenv"] = dotenv_mod

telemetry_mod = types.ModuleType("telemetry")
telemetry_mod.track_event = lambda name, props=None: record["telemetry"].append([name, props])
telemetry_mod.track_crash = lambda exc: record["telemetry"].append(["cli_crashed", type(exc).__name__])
telemetry_mod.flush_telemetry = lambda: record["telemetry"].append(["flush", None])
sys.modules["telemetry"] = telemetry_mod
sys.modules["src.telemetry"] = telemetry_mod

time.sleep = lambda seconds: record["sleeps"].append(seconds)


# --- Run ----------------------------------------------------------------------

gh_output = tempfile.NamedTemporaryFile("w", delete=False, suffix=".out")
gh_output.close()
os.environ["GITHUB_OUTPUT"] = gh_output.name
os.environ["GITHUB_TOKEN"] = "fake-token"
os.environ["GOOGLE_API_KEY"] = "fake-google-key"
os.environ["REPO_NAME"] = scenario.get("repo_name", "reem-sab/doc-sentinel-ai")
for key in ("PR_NUMBER", "ISSUE_NUMBER"):
    os.environ.pop(key, None)
    if scenario.get(key):
        os.environ[key] = str(scenario[key])
for key in ("DOC_SENTINEL_CHECKER_PROVIDER", "DOC_SENTINEL_CHECKER_MODEL"):
    os.environ.pop(key, None)
for key, value in scenario.get("env", {}).items():
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value

report_dir = tempfile.mkdtemp()
report_path = os.path.join(report_dir, "report.md")
sys.argv = [audit_path] + [a.replace("{report}", report_path) for a in scenario.get("argv", [])]

# Same import path as `python src/audit.py`: the script's folder first.
# The real src/ folder comes next so the refactored audit.py finds drift_core.
real_src = os.path.join(os.path.dirname(__file__), "..", "..", "src")
# The repo root comes last so historical_audit.py finds `src.drift_core`.
sys.path[:0] = [os.path.dirname(os.path.abspath(audit_path)), os.path.abspath(real_src),
                os.path.abspath(os.path.join(real_src, ".."))]

stdout = io.StringIO()
exit_code = 0
with contextlib.redirect_stdout(stdout):
    try:
        runpy.run_path(audit_path, run_name="__main__")
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except BaseException as e:
        exit_code = "uncaught " + type(e).__name__ + ": " + str(e)

record["stdout"] = stdout.getvalue().replace(report_path, "{report}")
if os.path.exists(report_path):
    record["report_file"] = open(report_path, encoding="utf-8").read()
    os.unlink(report_path)
os.rmdir(report_dir)
record["exit_code"] = exit_code
record["github_output"] = open(gh_output.name, encoding="utf-8").read()
os.unlink(gh_output.name)

with open(output_path, "w", encoding="utf-8") as f:
    json.dump(record, f, indent=2, ensure_ascii=False)
