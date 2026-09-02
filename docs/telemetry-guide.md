# Instrumenting Local CLI Frameworks with PostHog

This is the integration blueprint for the anonymous telemetry layer in
Doc-Sentinel AI. It covers how we run product analytics from a short-lived,
state-less command-line process without leaking PII, blocking the terminal, or
losing events when the process exits.

The implementation lives in [`src/telemetry.py`](../src/telemetry.py). The call
sites are in [`historical_audit.py`](../historical_audit.py) (the argparse CLI)
and [`src/audit.py`](../src/audit.py) (the GitHub Actions audit engine). To turn
the captured events into charts, see the companion
[dashboard guide](./telemetry-dashboard.md).

---

## Architectural Objectives

Analytics for a web app and analytics for a CLI are not the same problem. A web
server is a long-lived process with a persistent event loop; a dropped analytics
call is a rounding error against millions of requests. A CLI is the opposite: it
boots, does one job, and dies — often in under a second. Every constraint below
falls out of that difference.

**Never block the main thread.** The audit is the product; telemetry is a
side-effect. A network call to an ingestion endpoint can hang on DNS, a captive
portal, or a corporate proxy. The PostHog SDK already batches captures onto a
background consumer thread, so `capture()` returns immediately and enqueues.
We never issue a synchronous HTTP call on the path the user is waiting on.

**Fail open, always.** If the analytics backend is down, misconfigured, or the
key is absent, the tool must still audit documentation flawlessly. Every public
function in `telemetry.py` wraps its body in a bare `try/except` and swallows the
error. There is no code path where a telemetry failure can raise into the audit
logic. Import is defensive too — if `posthog` isn't installed, the call sites
fall back to no-op stubs:

```python
try:
    from src.telemetry import track_event, flush_telemetry
except Exception:  # telemetry is strictly best-effort
    def track_event(*args, **kwargs):
        pass

    def flush_telemetry(*args, **kwargs):
        pass
```

**Preserve terminal execution speed.** Background-thread isolation keeps the hot
path fast, but it introduces the teardown problem: the process can exit before
the consumer thread drains its queue. That is the single hardest part of CLI
analytics and it gets its own section below.

**Disable cleanly for local dev.** A contributor running the tool on their laptop
should generate zero network traffic by default. We resolve a disabled flag once
at import time and hand it straight to the SDK via `posthog.disabled`, which
short-circuits `capture()` and `flush()` inside the library itself — no queue, no
socket, no thread wakeups.

```python
_TELEMETRY_DISABLED = (
    os.environ.get("DOC_SENTINEL_TELEMETRY_DISABLED", "").lower() == "true"
    or not POSTHOG_API_KEY
)
posthog.disabled = _TELEMETRY_DISABLED
```

Telemetry is off unless a `POSTHOG_API_KEY` is present **and** the operator has
not explicitly opted out. Absence of configuration means silence, not errors.

---

## Privacy Guardrails

We want to answer product questions — Do people run repeat audits? How much drift
does the tool catch in the wild? — without ever learning *who* is running it. The
mechanism is a machine identity derived from a one-way hash.

**The identity function.** We build a distinct ID from the local hostname joined
with the current working directory, hash it with SHA-256, and truncate to 16 hex
characters:

```python
def get_anonymous_id():
    hostname = socket.gethostname()
    seed = hostname + "|" + os.getcwd()
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return digest[:16]
```

**Why this preserves retention without PII.** The property that makes retention
analysis possible is *stability*: the same machine, run from the same checkout
directory, always produces the same ID. That lets PostHog stitch repeat runs into
a single anonymous user and compute action continuity — day-2, day-7 retention,
runs-per-user — across sessions.

The property that makes it private is *irreversibility*. SHA-256 is a one-way
function; truncating to 16 characters discards even more preimage information.
What actually crosses the wire is a value like `2171f6896eb459b5`. From that:

- **No usernames.** The hostname is hashed, never sent in the clear.
- **No file paths.** `os.getcwd()` is folded into the digest, so we get a stable
  per-workspace signal without ever transmitting an absolute path that might
  contain a username (`/home/alice/...`) or a client name (`/work/acme-corp/...`).
- **No private network identifiers.** Corporate hostnames — which frequently
  encode team, office, or asset-tag information — never leave the machine as
  readable text.

We deliberately combine hostname **and** working directory rather than using
either alone. Hostname alone would collapse every repo on one machine into a
single user; working directory alone is not unique enough across machines. The
pair gives us "this developer, working on this checkout" — the right grain for
adoption analysis — while remaining non-reversible.

---

## Managing Process Interruption

The background consumer thread is what keeps the CLI fast, and it is also what
can silently eat your events. Here is the failure mode, precisely:

1. `track_event()` enqueues an event onto the SDK's in-memory queue and returns.
2. The consumer thread flushes the queue to PostHog on a timer (batched).
3. The CLI finishes its work and the interpreter begins shutting down.
4. If the process exits **before** the next scheduled flush, the queued events
   are still in memory. They are never sent. This is *event clipping*.

For a web server this rarely bites, because the process lives for hours. For a
CLI that exits in 800ms, it bites almost every time. The fix is an explicit,
blocking flush in a teardown path that is guaranteed to run:

```python
def flush_telemetry():
    if _TELEMETRY_DISABLED:
        return
    try:
        posthog.flush()   # blocks until the consumer queue is drained
    except Exception:
        pass
```

`flush()` forces the consumer to empty its queue synchronously and blocks until
it finishes — so it belongs at the very end of execution, never on the hot path.

**Put the call in a `finally` block, not after the last statement.** A CLI has
many exit paths: normal completion, `sys.exit()`, and unhandled exceptions. Only
`finally` covers all three. Note that `sys.exit()` raises `SystemExit`, so a bare
"call flush on the last line" misses every early exit.

In the argparse CLI we wrap the entry point:

```python
if __name__ == "__main__":
    try:
        main()
    finally:
        flush_telemetry()   # runs on completion, sys.exit(), or error
```

In the GitHub Actions engine, each trigger branch already has its own
`try/except`, so the flush hangs off each `finally`:

```python
try:
    # ... run the PR / issue audit ...
except Exception as e:
    print("CRITICAL ERROR: " + str(e))
    sys.exit(1)
finally:
    flush_telemetry()       # drain before the runner reaps the process
```

The rule: **capture on the hot path, flush on teardown, and make teardown
unconditional.**

---

## Example Schema

Three events are instrumented across the two entry points. Every event also carries
the global context properties injected automatically by `track_event()`:
`os_platform` (str), `tool_version` (str), and `is_ci` (bool).

### `cli_audit_started`

Fired once per invocation, immediately after arguments/triggers are parsed. It
records what the operator turned on — never who they are.

| Property              | Type   | Description                                                                 |
| :-------------------- | :----- | :-------------------------------------------------------------------------- |
| `scan_type`           | string | `all_docs` / `matched_only` (CLI) or `pull_request` / `doc_detective_issue` (Actions) |
| `custom_config_found` | bool   | Whether a `sentinel.yaml` config file is present in the working directory   |
| `custom_output`       | bool   | CLI only — a non-default `--output` path was supplied                       |
| `token_from_flag`     | bool   | CLI only — the GitHub token came from `--token` rather than the environment |
| `key_from_flag`       | bool   | CLI only — the Google API key came from `--key` rather than the environment |
| `trigger_source`      | string | Actions only — the invocation source, e.g. `github_actions`                 |

### `drift_detected`

Fired when the audit catches documentation drift, to measure the volume and
severity of issues the tool surfaces in the wild.

| Property           | Type   | Description                                                              |
| :----------------- | :----- | :----------------------------------------------------------------------- |
| `drift_count`      | int    | Number of documents (or failures) with detected drift in this run        |
| `highest_severity` | string | Worst severity seen: `critical` / `minor` (Actions) or `OUTDATED` / `PARTIAL` (CLI) |
| `files_audited`    | int    | Total number of files inspected during the run                           |

### `cli_crashed`

Fired when a run terminates on an unhandled exception, to measure which failure
modes users hit most. It carries **only the exception class name** — never the
message or traceback, which routinely contain file paths and hostnames and would
break the anonymization guarantees.

| Property     | Type   | Description                                            |
| :----------- | :----- | :---------------------------------------------------- |
| `error_type` | string | The exception's class name, e.g. `ValueError`, `KeyError` |

---

## Configuration Reference

| Variable                          | Default                  | Purpose                                        |
| :-------------------------------- | :----------------------- | :--------------------------------------------- |
| `POSTHOG_API_KEY`                 | *(unset → disabled)*     | PostHog project API key. Absence disables all collection. |
| `POSTHOG_HOST`                    | `https://posthog.com`    | Ingestion host. Empty values fall back to the default. |
| `DOC_SENTINEL_TELEMETRY_DISABLED` | `false`                  | Set to `true` to opt out entirely, key present or not. |
