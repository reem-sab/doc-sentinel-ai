"""
Scenarios for the audit.py before/after comparison.

The fake repository is the real file tree of the baseline commit, so file
mapping runs against the actual sample docs. Gemini replies are scripted
per doc and written in the format the audit prompt asks for.
"""

REPLY_CRITICAL = """**DRIFT AUDIT**
**YES** The docs tell users to call `start_ai_audit(api_key)`, but the code now exposes `initialize_user_session(user_id, session_timeout)`.
🔴 CRITICAL

Suggested Fix
```markdown
To start a session, call `initialize_user_session(user_id, session_timeout)`.
```

**STYLE AUDIT**
- Replace the opening "This function" with the function name.
- Add a `## Parameters` section."""

REPLY_MINOR = """**DRIFT AUDIT**
**YES** The dashboard guide still lists two events, but the code now also sends `cli_crashed`.
🟡 MINOR

Suggested Fix
```markdown
| `cli_crashed` | A run ends on an unhandled exception |
```

**STYLE AUDIT**
- Label the event table columns consistently."""

REPLY_NO = """**DRIFT AUDIT**
**NO** The documented behaviour still matches the code.

**STYLE AUDIT**
- Add a language label to the second code block."""

REPLY_BARE_YES = """YES — the timeout unit changed from milliseconds to seconds and the docs still say ms.
🔴 CRITICAL

**STYLE AUDIT**
- Spell out the unit in the parameter table."""

REPLY_LOWERCASE_YES = """**DRIFT AUDIT**
**Yes** The example uses the old parameter name.
🟡 MINOR

**STYLE AUDIT**
- None."""

REPLY_ISSUE = """**FAILURE AUDIT**
The guide documents `start_ai_audit(api_key)`, which no longer exists, so the code step fails.
🔴 CRITICAL

**SUGGESTED FIX**
```markdown
`initialize_user_session(user_id, session_timeout)`
```

**STYLE AUDIT**
- Name the function in the first sentence."""

AUTH_PATCH = """@@ -1,7 +1,7 @@
 # auth_service.py

-def initialize_user_session(user_id, session_timeout):
+def initialize_user_session(user_id, session_timeout, remember_me=False):
     \"\"\"
     Starts a new session for a verified user.
     \"\"\"
-    print(f"Session started for {user_id} with a {session_timeout}ms timeout.")
+    print(f"Session started for {user_id} with a {session_timeout}s timeout.")
     return True"""

TELEMETRY_PATCH = """@@ -128,3 +128,7 @@ def track_crash(exception):
     track_event("cli_crashed", {"error_type": type(exception).__name__})
+
+
+def track_retry(attempt):
+    track_event("cli_retry", {"attempt": attempt})"""

AUDIT_PATCH = """@@ -40,6 +40,7 @@ class DocSentinelIntelligence:
         if not re.search(r'^## ', self.content, re.M):
             score -= 20
+        # Headings are worth more now.
         return max(score, 0)"""

README_PATCH = """@@ -1,3 +1,3 @@
-# Doc-Sentinel AI: Agentic Documentation Governance
+# Doc-Sentinel AI: Agentic Documentation Governance (beta)"""

DOC_DETECTIVE_ISSUE = """Doc Detective found failures.

```json
{
  "specs": [
    {
      "file": "/home/runner/work/doc-sentinel-ai/doc-sentinel-ai/getting-started.md",
      "result": "FAIL",
      "tests": [{"contexts": [{"steps": [
        {"action": "runCode", "result": "FAIL", "resultDescription": "start_ai_audit is not defined"},
        {"action": "checkLink", "result": "PASS", "resultDescription": "ok"}
      ]}]}]
    },
    {"file": "/home/runner/work/doc-sentinel-ai/doc-sentinel-ai/api-reference.md", "result": "PASS", "tests": []}
  ]
}
```"""


def doc_rule(doc_path, reply, errors=None):
    """Scripted reply for the audit of one doc, matched on the prompt's doc header."""
    rule = {"match": "EXISTING DOCS (" + doc_path + "):", "reply": reply}
    if errors:
        rule["errors"] = errors
    return rule


SCENARIOS = {
    "pr_fallback_critical": {
        "about": "auth_service.py changes; no doc name matches, so it falls back to getting-started.md. CRITICAL drift.",
        "PR_NUMBER": 7,
        "pr_files": [["src/auth_service.py", AUTH_PATCH]],
        "gemini": [doc_rule("getting-started.md", REPLY_CRITICAL)],
    },
    "pr_multi_file_mixed": {
        "about": "4 changed files incl. a binary; maps to 4 docs with NO, MINOR, CRITICAL, NO.",
        "PR_NUMBER": 8,
        "pr_files": [
            ["src/telemetry.py", TELEMETRY_PATCH],
            ["src/audit.py", AUDIT_PATCH],
            ["README.md", README_PATCH],
            ["assets/logo.png", None],
        ],
        "gemini": [
            doc_rule("docs/telemetry-guide.md", REPLY_NO),
            doc_rule("docs/telemetry-dashboard.md", REPLY_MINOR),
            doc_rule("getting-started.md", REPLY_CRITICAL),
            doc_rule("README.md", REPLY_NO),
        ],
    },
    "pr_minor_only": {
        "about": "Only MINOR drift: label is Docs: Action Required.",
        "PR_NUMBER": 9,
        "pr_files": [["src/telemetry.py", TELEMETRY_PATCH]],
        "gemini": [
            doc_rule("docs/telemetry-guide.md", REPLY_MINOR),
            doc_rule("docs/telemetry-dashboard.md", REPLY_NO),
        ],
    },
    "pr_all_clear": {
        "about": "No drift anywhere: label is Docs: Passed, no drift telemetry.",
        "PR_NUMBER": 10,
        "pr_files": [["src/telemetry.py", TELEMETRY_PATCH]],
        "gemini": [
            doc_rule("docs/telemetry-guide.md", REPLY_NO),
            doc_rule("docs/telemetry-dashboard.md", REPLY_NO),
        ],
    },
    "pr_doc_unreadable": {
        "about": "A matched doc cannot be fetched: warning section, other docs still audited.",
        "PR_NUMBER": 11,
        "unreadable": ["docs/telemetry-guide.md"],
        "pr_files": [["src/telemetry.py", TELEMETRY_PATCH]],
        "gemini": [doc_rule("docs/telemetry-dashboard.md", REPLY_NO)],
    },
    "pr_scan_failure": {
        "about": "Listing the repo fails: prints the error and audits getting-started.md.",
        "PR_NUMBER": 12,
        "scan_error": "403 rate limit exceeded",
        "pr_files": [["src/telemetry.py", TELEMETRY_PATCH]],
        "gemini": [doc_rule("getting-started.md", REPLY_NO)],
    },
    "pr_rate_limited_then_ok": {
        "about": "Gemini returns 429 twice, then answers: two 30 s sleeps, same comment.",
        "PR_NUMBER": 13,
        "pr_files": [["src/auth_service.py", AUTH_PATCH]],
        "gemini": [doc_rule("getting-started.md", REPLY_CRITICAL,
                            errors=["429 RESOURCE_EXHAUSTED", "429 RESOURCE_EXHAUSTED"])],
    },
    "pr_rate_limit_exhausted": {
        "about": "Gemini returns 429 three times: run fails with exit 1 and a crash event.",
        "PR_NUMBER": 14,
        "pr_files": [["src/auth_service.py", AUTH_PATCH]],
        "gemini": [doc_rule("getting-started.md", REPLY_CRITICAL, errors=["429 RESOURCE_EXHAUSTED"] * 3)],
    },
    "pr_api_error": {
        "about": "Gemini fails with a non-429 error: no retry, exit 1.",
        "PR_NUMBER": 15,
        "pr_files": [["src/auth_service.py", AUTH_PATCH]],
        "gemini": [doc_rule("getting-started.md", REPLY_CRITICAL, errors=["400 API key not valid"])],
    },
    "pr_bare_yes": {
        "about": "Reply starts with an unbolded YES: still counted as drift.",
        "PR_NUMBER": 16,
        "pr_files": [["src/auth_service.py", AUTH_PATCH]],
        "gemini": [doc_rule("getting-started.md", REPLY_BARE_YES)],
    },
    "pr_lowercase_yes": {
        "about": "Reply says **Yes**: the Action does not count it (existing behaviour, kept as is).",
        "PR_NUMBER": 17,
        "pr_files": [["src/auth_service.py", AUTH_PATCH]],
        "gemini": [doc_rule("getting-started.md", REPLY_LOWERCASE_YES)],
    },
    "issue_doc_detective": {
        "about": "Doc Detective issue: parses the JSON report and comments on the issue.",
        "ISSUE_NUMBER": 21,
        "issue_body": DOC_DETECTIVE_ISSUE,
        "gemini": [{"match": "FAILURE SUMMARY", "reply": REPLY_ISSUE}],
    },
    "issue_without_report": {
        "about": "Issue body has no JSON report: exit 1.",
        "ISSUE_NUMBER": 22,
        "issue_body": "Something broke, no report attached.",
        "gemini": [],
    },
    "no_trigger": {
        "about": "Push event with no PR or issue number: exits 0.",
        "gemini": [],
    },
}
