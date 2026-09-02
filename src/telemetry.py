"""
Doc-Sentinel AI — Anonymous Developer Telemetry
-----------------------------------------------
Privacy-first, fail-open instrumentation built on the PostHog Python SDK.

Design goals:
    * Never crash the audit tool. Every public function swallows its own
      errors so a broken/offline analytics backend can't take down a run.
    * Never capture PII. No usernames, no absolute file paths, no repo URLs.
      Machine identity is a truncated, non-reversible SHA-256 digest.
    * Respect the operator. A single env var fully disables collection.

Environment variables:
    POSTHOG_API_KEY                 Project API key. If unset, telemetry is off.
    POSTHOG_HOST                    Ingestion host (default: https://posthog.com).
    DOC_SENTINEL_TELEMETRY_DISABLED Set to "true" to opt out entirely.
"""

import os
import hashlib
import socket
import platform

import posthog


# Semantic version reported as global context on every event.
TOOL_VERSION = "1.0.0"

# --- CONFIGURATION ------------------------------------------------------------

POSTHOG_API_KEY = os.environ.get("POSTHOG_API_KEY")
# `or` (not a get default) so an empty env var — e.g. an unset CI secret that
# renders as "" — still falls back to the public host instead of a blank URL.
POSTHOG_HOST = os.environ.get("POSTHOG_HOST") or "https://posthog.com"

# Telemetry is disabled if the operator opts out OR no API key is present.
# We resolve this once at import time and, critically, tell the SDK to become
# a no-op so stray capture()/flush() calls never open a socket or raise.
_TELEMETRY_DISABLED = (
    os.environ.get("DOC_SENTINEL_TELEMETRY_DISABLED", "").lower() == "true"
    or not POSTHOG_API_KEY
)

posthog.api_key = POSTHOG_API_KEY
posthog.host = POSTHOG_HOST
# posthog.disabled short-circuits capture()/flush() inside the SDK itself,
# which keeps local dev runs from touching the network or throwing.
posthog.disabled = _TELEMETRY_DISABLED


# --- IDENTITY -----------------------------------------------------------------

def get_anonymous_id():
    """
    Return a stable, non-reversible identifier for this machine + workspace.

    The digest is derived from the local hostname combined with the current
    working directory. Same machine + same checkout location -> same id across
    runs, which is what lets us measure retention. The SHA-256 hash is
    truncated to 16 hex characters so the raw hostname and path can never be
    recovered from the wire — no usernames, no absolute paths leave the box.
    """
    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = "unknown-host"

    seed = hostname + "|" + os.getcwd()
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return digest[:16]


# --- GLOBAL CONTEXT -----------------------------------------------------------

def _global_context():
    """Properties attached automatically to every captured event."""
    return {
        "os_platform": platform.system(),
        "tool_version": TOOL_VERSION,
        "is_ci": "GITHUB_ACTIONS" in os.environ,
    }


# --- PUBLIC API ---------------------------------------------------------------

def track_event(event_name, properties=None):
    """
    Capture a single analytics event, fail-open.

    Merges caller-supplied `properties` with the automatic global context and
    sends it to PostHog under the anonymous id. Any failure — SDK disabled,
    network down, bad key — is swallowed so the audit workflow keeps running.
    """
    if _TELEMETRY_DISABLED:
        return
    try:
        payload = _global_context()
        if properties:
            payload.update(properties)

        # PostHog SDK >= 6.0 takes the event name positionally and requires
        # distinct_id as a keyword argument. Passing distinct_id positionally
        # (the pre-6.0 style) raises TypeError on modern SDKs.
        posthog.capture(
            event_name,
            distinct_id=get_anonymous_id(),
            properties=payload,
        )
    except Exception:
        # Telemetry must never break the tool. Stay silent.
        pass


def track_crash(exception):
    """
    Record that a run terminated on an unhandled exception, fail-open.

    Privacy note: we send only the exception's class name (e.g. "ValueError"),
    never the message or traceback. Exception messages routinely contain file
    paths, hostnames, and other identifying strings, so capturing them would
    defeat the anonymization guarantees. The class name alone is enough to see
    which failure modes users hit most.
    """
    track_event("cli_crashed", {"error_type": type(exception).__name__})


def flush_telemetry():
    """
    Force the PostHog background consumer to drain its queue.

    The SDK batches events on a background thread and flushes on an interval.
    Our CLI exits almost immediately after the final event, so without an
    explicit flush the process can terminate before the queue is emptied and
    events get clipped. Call this in a teardown / finally block right before
    the process exits. Fail-open like everything else here.
    """
    if _TELEMETRY_DISABLED:
        return
    try:
        posthog.flush()
    except Exception:
        pass
