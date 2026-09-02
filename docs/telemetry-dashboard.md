# Building the Doc-Sentinel Telemetry Dashboard in PostHog

This guide turns the three instrumented events (`cli_audit_started`, `drift_detected`,
`cli_crashed`) into a dashboard that answers the questions the tool was built to
answer: how much it is used, how much drift it catches, and what breaks.

Every tile is given two ways to build it: the **point-and-click** path (PostHog's
Trends builder, no query language) and the equivalent **HogQL** query for anyone
who prefers SQL. Pick whichever you like — they produce the same numbers.

## Prerequisites

- Events are flowing (see [`telemetry-guide.md`](./telemetry-guide.md)). Confirm at
  least one `cli_audit_started` event is visible under **Activity**.
- You are on a project where you can create insights and dashboards.

## Create the dashboard

1. Left sidebar → **Dashboards** → **New dashboard** → start blank.
2. Name it `Doc-Sentinel Telemetry`.
3. Add each tile below with **Add insight** → **New insight**.

---

## Tiles

### 1. Audits over time

The core usage heartbeat: how often the tool runs.

- **Click path:** Trends → series event `cli_audit_started` → measure **Total count** → chart type **Line** → interval **Day**.
- **HogQL:**
  ```sql
  SELECT toStartOfDay(timestamp) AS day, count() AS audits
  FROM events
  WHERE event = 'cli_audit_started'
  GROUP BY day
  ORDER BY day
  ```

### 2. Returning machines per week (retention proxy)

Distinct anonymous IDs per week. Because the ID is stable per machine + workspace,
a flat-or-rising line means people come back.

- **Click path:** Trends → event `cli_audit_started` → measure **Unique users** → interval **Week**.
- **HogQL:**
  ```sql
  SELECT toStartOfWeek(timestamp) AS week, count(DISTINCT person_id) AS machines
  FROM events
  WHERE event = 'cli_audit_started'
  GROUP BY week
  ORDER BY week
  ```

### 3. Drift detection rate

Of all audits, how many caught drift. This is the "is the tool earning its keep"
number.

- **Click path:** Trends → add two series: `drift_detected` (Total count) and
  `cli_audit_started` (Total count) → chart type **Number** or **Line**; read the
  ratio, or use the formula field `A / B`.
- **HogQL:**
  ```sql
  SELECT
    countIf(event = 'drift_detected')    AS drift_runs,
    countIf(event = 'cli_audit_started') AS total_runs,
    round(100.0 * countIf(event = 'drift_detected')
                / nullIf(countIf(event = 'cli_audit_started'), 0), 1) AS drift_rate_pct
  FROM events
  WHERE event IN ('drift_detected', 'cli_audit_started')
  ```

### 4. Scan-type breakdown

Which entry points and modes people actually use (`all_docs`, `matched_only`,
`pull_request`, `doc_detective_issue`).

- **Click path:** Trends → event `cli_audit_started` → **Break down by** →
  event property `scan_type` → chart type **Pie**.
- **HogQL:**
  ```sql
  SELECT properties.scan_type AS scan_type, count() AS runs
  FROM events
  WHERE event = 'cli_audit_started'
  GROUP BY scan_type
  ORDER BY runs DESC
  ```

### 5. Drift severity mix

How serious the drift being caught is (`critical` / `minor`).

- **Click path:** Trends → event `drift_detected` → **Break down by** →
  property `highest_severity` → chart type **Bar**.
- **HogQL:**
  ```sql
  SELECT properties.highest_severity AS severity, count() AS occurrences
  FROM events
  WHERE event = 'drift_detected'
  GROUP BY severity
  ORDER BY occurrences DESC
  ```

### 6. Total drift instances caught

The cumulative count of drifting docs the tool has flagged.

- **Click path:** Trends → event `drift_detected` → measure **Property sum of** →
  `drift_count` → chart type **Number**.
- **HogQL:**
  ```sql
  SELECT sum(toInt(properties.drift_count)) AS total_drift_caught
  FROM events
  WHERE event = 'drift_detected'
  ```

### 7. Failure modes by type

Which exceptions users hit most, from the `cli_crashed` event. Only the exception
class name is captured — never messages or tracebacks.

- **Click path:** Trends → event `cli_crashed` → **Break down by** →
  property `error_type` → chart type **Bar**.
- **HogQL:**
  ```sql
  SELECT properties.error_type AS error_type, count() AS hits
  FROM events
  WHERE event = 'cli_crashed'
  GROUP BY error_type
  ORDER BY hits DESC
  ```

### 8. CI vs local usage

Whether runs come from GitHub Actions or developer machines (`is_ci`).

- **Click path:** Trends → event `cli_audit_started` → **Break down by** →
  property `is_ci` → chart type **Pie**.
- **HogQL:**
  ```sql
  SELECT properties.is_ci AS is_ci, count() AS runs
  FROM events
  WHERE event = 'cli_audit_started'
  GROUP BY is_ci
  ```

---

## Share the dashboard publicly

To link the dashboard from a blog post or portfolio without making viewers log in:

1. Open the dashboard → **Share** (top right).
2. Toggle **Share publicly** on.
3. Copy the generated public URL. Anyone with the link sees a read-only view.

Public sharing exposes whatever is on the dashboard, so keep it to aggregate tiles
like the ones above — no per-person drill-downs.

## A note on test events

While validating the pipeline you may have sent events with `scan_type = "manual_test"`.
To keep those out of the real numbers, add a global dashboard filter for
`scan_type ≠ manual_test`, or delete the test events under **Activity**.
