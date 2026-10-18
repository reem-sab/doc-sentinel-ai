"""
Unit tests for src/drift_core.py: the verdict rules, doc mapping, checker
configuration, and local checkout helpers.
"""

import os
import sys
import subprocess

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests", "equivalence"))
from src import drift_core  # noqa: E402
from src.drift_core import parse_drift_audit, has_drift  # noqa: E402
import scenarios  # noqa: E402


# --- Verdict rules ------------------------------------------------------------

@pytest.mark.parametrize("reply,status,drift,severity", [
    (scenarios.REPLY_NO, "pass", False, None),
    (scenarios.REPLY_MINOR, "pass", True, "minor"),
    (scenarios.REPLY_CRITICAL, "fail", True, "critical"),
    (scenarios.REPLY_BARE_YES, "fail", True, "critical"),
    # The Action misses a lowercase **Yes**; the agent's check must not.
    (scenarios.REPLY_LOWERCASE_YES, "pass", True, "minor"),
    ("**DRIFT AUDIT**\n**Yes** The endpoint was removed.\n🔴 CRITICAL", "fail", True, "critical"),
    # Markdown headings instead of bold ones.
    ("### DRIFT AUDIT\n**NO** Docs match the code.\n\n### STYLE AUDIT\n- Note the MINOR typo.", "pass", False, None),
    ("## DRIFT AUDIT\n**YES** Wrong default.\nSeverity: 🟡 MINOR\n## STYLE AUDIT\n- x", "pass", True, "minor"),
    # Severity on the same line as the verdict.
    ("**DRIFT AUDIT**\n**YES** 🟡 MINOR — the example uses `timeout` instead of `timeout_ms`.", "pass", True, "minor"),
    # Both labels present: the stricter one wins.
    ("**DRIFT AUDIT**\n**YES** Signature changed.\n- 🔴 CRITICAL\n- 🟡 MINOR", "fail", True, "critical"),
    # Drift without a severity label fails.
    ("**DRIFT AUDIT**\n**YES** Something changed.\n\n**STYLE AUDIT**\n- x", "fail", True, None),
    # No verdict at all fails.
    ("I could not compare these files.", "fail", None, None),
    ("", "fail", None, None),
    # "Note" must not read as "NO".
    ("**DRIFT AUDIT**\n**Note:** the diff is empty.", "fail", None, None),
])
def test_verdict_rules(reply, status, drift, severity):
    verdict = parse_drift_audit(reply, fail_on_minor=False)
    assert (verdict.status, verdict.drift, verdict.severity) == (status, drift, severity)
    assert verdict.raw == reply


def test_never_more_lenient_than_the_action():
    """Anything the Action counts as drift is drift for the agent too."""
    for name in dir(scenarios):
        if name.startswith("REPLY_"):
            reply = getattr(scenarios, name)
            if has_drift(reply):
                assert parse_drift_audit(reply).drift is True, name


def test_fail_on_minor_from_argument_and_environment(monkeypatch):
    assert parse_drift_audit(scenarios.REPLY_MINOR, fail_on_minor=True).status == "fail"
    monkeypatch.setenv("DOC_SENTINEL_FAIL_ON_MINOR", "true")
    assert parse_drift_audit(scenarios.REPLY_MINOR).status == "fail"
    monkeypatch.setenv("DOC_SENTINEL_FAIL_ON_MINOR", "")
    assert parse_drift_audit(scenarios.REPLY_MINOR).status == "pass"


def test_explanation_fix_and_style_notes_are_extracted():
    v = parse_drift_audit(scenarios.REPLY_CRITICAL)
    assert v.explanation.startswith("The docs tell users to call `start_ai_audit(api_key)`")
    assert "YES" not in v.explanation and "CRITICAL" not in v.explanation
    assert v.suggested_fix.startswith("```markdown") and "initialize_user_session" in v.suggested_fix
    assert v.style_notes == ['Replace the opening "This function" with the function name.',
                             "Add a `## Parameters` section."]

    same_line = parse_drift_audit("**DRIFT AUDIT**\n**YES** 🟡 MINOR — the example uses `timeout`.")
    assert same_line.explanation == "the example uses `timeout`."
    labelled = parse_drift_audit("## DRIFT AUDIT\n**YES** Wrong default.\nSeverity: 🟡 MINOR")
    assert labelled.explanation == "Wrong default."


# --- Doc mapping (same rules as the Action) -------------------------------------

SAMPLE_DOCS = ["README.md", "AI_STYLE_GUIDE.md", "api-reference.md", "getting-started.md",
               "docs/telemetry-guide.md", "docs/telemetry-dashboard.md"]


def test_match_docs_on_the_sample_docs():
    by_file = drift_core.match_docs_by_file(SAMPLE_DOCS, ["src/telemetry.py", "src/auth_service.py", "src/api_reference.py"])
    assert by_file == {
        "src/telemetry.py": ["docs/telemetry-guide.md", "docs/telemetry-dashboard.md"],
        "src/auth_service.py": [],
        "src/api_reference.py": ["api-reference.md"],
    }
    assert sorted(drift_core.match_docs(SAMPLE_DOCS, ["src/auth_service.py"])) == ["getting-started.md"]
    assert drift_core.match_docs(SAMPLE_DOCS, []) == ["getting-started.md"]


def test_format_diff_skips_files_without_a_patch():
    text, files = drift_core.format_diff([("a.py", "@@ -1 +1 @@\n-x\n+y"), ("logo.png", None), ("b.py", "")])
    assert text == "File: a.py\n@@ -1 +1 @@\n-x\n+y\n\n"
    assert files == ["a.py"]


# --- Checker configuration ------------------------------------------------------

def test_checker_defaults_to_gemini(monkeypatch):
    monkeypatch.delenv("DOC_SENTINEL_CHECKER_PROVIDER", raising=False)
    monkeypatch.setenv("DOC_SENTINEL_CHECKER_MODEL", "")  # empty CI secret
    assert drift_core.checker_settings() == {"provider": "gemini", "model": "gemini-2.0-flash"}


def test_checker_model_and_provider_are_configurable(monkeypatch):
    seen = {}
    monkeypatch.setitem(drift_core.PROVIDERS, "other", lambda prompt, model, log: seen.update(model=model) or "ok")
    monkeypatch.setenv("DOC_SENTINEL_CHECKER_PROVIDER", "other")
    monkeypatch.setenv("DOC_SENTINEL_CHECKER_MODEL", "other-model-1")
    assert drift_core.run_checker("prompt") == "ok"
    assert seen == {"model": "other-model-1"}

    monkeypatch.setenv("DOC_SENTINEL_CHECKER_PROVIDER", "nope")
    with pytest.raises(ValueError, match="Unknown checker provider 'nope'"):
        drift_core.run_checker("prompt")


# --- Local checkout helpers -----------------------------------------------------

def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                   check=True, capture_output=True)


def test_local_diff_handles_renames_deletes_binaries_and_spaces(tmp_path):
    repo = tmp_path
    _git(repo, "init", "-q")
    (repo / "keep.py").write_text("a = 1\n")
    (repo / "old name.py").write_text("x = 1\n" * 5)
    (repo / "gone.py").write_text("y = 1\n")
    (repo / "logo.png").write_bytes(b"\x89PNG\x00\x01")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    (repo / "keep.py").write_text("a = 2\n")
    _git(repo, "mv", "old name.py", "new name.py")
    (repo / "new name.py").write_text("x = 1\n" * 4 + "x = 2\n")
    (repo / "gone.py").unlink()
    (repo / "logo.png").write_bytes(b"\x89PNG\x00\x02")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")

    patches = dict(drift_core.local_file_patches(repo, "HEAD~1..HEAD"))
    assert set(patches) == {"keep.py", "new name.py", "gone.py", "logo.png"}
    assert patches["keep.py"] == "@@ -1 +1 @@\n-a = 1\n+a = 2"
    assert patches["new name.py"].startswith("@@ ") and "+x = 2" in patches["new name.py"]
    assert patches["gone.py"] == "@@ -1 +0,0 @@\n-y = 1"
    assert patches["logo.png"] is None

    text, files = drift_core.local_diff(repo, "HEAD~1..HEAD")
    assert sorted(files) == ["gone.py", "keep.py", "new name.py"]


@pytest.mark.parametrize("bad", ["", "--output=/tmp/x", "-p", "a b", "HEAD\n--x"])
def test_invalid_ranges_are_rejected(bad):
    with pytest.raises(ValueError):
        drift_core.validate_diff_range(bad)


def test_doc_paths_must_stay_inside_the_repo(tmp_path):
    (tmp_path / "doc.md").write_text("hi")
    os.symlink("/etc/hostname", tmp_path / "link.md")
    assert drift_core.read_local_doc(tmp_path, "doc.md") == "hi"
    for bad in ["../x.md", "/etc/passwd", "link.md"]:
        with pytest.raises(ValueError, match="outside the repository"):
            drift_core.resolve_doc_path(tmp_path, bad)
