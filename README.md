# Doc-Sentinel AI: Agentic Documentation Governance

Doc-Sentinel AI audits your documentation on every code change, catching drift between your code and your docs before anything ships. It runs inside your continuous integration and continuous delivery (CI/CD) pipeline.

Built by a Senior Technical Writer who got tired of waiting for someone else to solve documentation debt.

See the [Doc-Sentinel AI landing page](https://reem-sab.github.io/doc-sentinel-ai/) for a live demo.

---

## The problem

Wrong documentation is more dangerous than no documentation.

When a developer follows outdated instructions with confidence and something breaks in production, that is not a people problem. It is a systems problem. Nobody flagged the drift. Nobody had a safety net.

Doc-Sentinel is that safety net. It hooks into your GitHub Actions pipeline, compares every code change against your documentation using artificial intelligence (AI), and posts its findings directly on the pull request before anything merges.

---

## Features

- **Multi-file drift detection:** Doc-Sentinel identifies which documentation files each code change affects and audits all of them in a single pull request comment.
- **Historical audit CLI:** Scan your entire repository for existing documentation drift in one command. You get a full health report across every `.md` file, not just what changes going forward.
- **Semantic integrity audits:** Gemini 2.0 Flash interprets the intent of code changes, catching logic shifts that regular expression linters miss.
- **Intelligence scoring:** Doc-Sentinel scores your documentation for AI readability using the [AI-Readability Style Guide](AI_STYLE_GUIDE.md), catching vague pronouns, broken heading hierarchy, dense paragraphs, and missing code block metadata.
- **Actionable remediation:** Doc-Sentinel posts a severity label, a one-sentence explanation, and a corrected Markdown snippet directly on the pull request, ready to paste in.
- **Zero-friction CI/CD:** Doc-Sentinel runs natively in GitHub Actions. No new tools, no new workflows.
- **Doc Detective integration:** When Doc Detective test failures appear, Doc-Sentinel audits the affected file and posts its findings back on the issue.
- **Self-instrumentation:** Anonymous, opt-in telemetry reports audit volume and drift rates to a public dashboard.

---

## The two-part audit

Every Doc-Sentinel run performs 2 distinct checks.

#### 1. Drift audit

Gemini compares the code diff against the existing documentation to detect technical drift, which includes changes to function signatures, parameters, renamed methods, or removed steps that the docs do not reflect. When Doc-Sentinel finds drift, the result starts with `YES` and it applies a `Docs: Action Required` label.

#### 2. Intelligence audit

The `DocSentinelIntelligence` engine scores the documentation for AI readability using the standards in the [AI-Readability Style Guide](AI_STYLE_GUIDE.md). It checks for the following.

| **Rule** | **What it catches** |
| -------- | ------------------- |
| Context persistence | Vague pronouns (It, This, They) at the start of paragraphs that cause AI chunking failures |
| Semantic hierarchy | Skipped heading levels that break the understanding AI crawlers have of document structure |
| Paragraph density | Walls of text that cause information dilution in retrieval-augmented generation (RAG) embeddings |
| Code block metadata | Unlabeled code blocks that prevent AI agents from identifying language and context |
| Visual-to-text bridging | Images without alt text that are invisible to text-only RAG pipelines |

Doc-Sentinel posts a resulting score of 0 to 100% on every pull request alongside the drift findings.

---

## Measuring itself

Doc-Sentinel reports its own behavior to PostHog, because a tool that audits documentation quality should be able to show its own evidence. See the [public telemetry dashboard](https://us.posthog.com/shared/fudAKtSiK2nY9RmXk1z_mqSjYE-2Gg) for current audit volume and drift rates.

Doc-Sentinel sends the following events.

| **Event** | **Fires when** |
| --------- | -------------- |
| `cli_audit_started` | An audit run begins, from either a pull request or the historical audit CLI |
| `drift_detected` | The drift audit finds code changes that the docs do not reflect |

Unhandled exceptions send the exception class name and nothing else.

Telemetry stays off unless you set `POSTHOG_API_KEY` yourself.

<!-- VERIFY before publishing: confirm the event property payloads in src/audit.py (lines 259, 319, 361) and historical_audit.py (lines 247, 347) exclude repository names and file paths, and check what src/telemetry.py hashes into the anonymous ID. Delete this comment once confirmed. -->
Doc-Sentinel never transmits documentation content, code, diffs, or repository names. An anonymous hashed ID identifies each run, which groups repeat runs from the same repository.

To disable telemetry when a key is present, set the following variable:

```text
DOC_SENTINEL_TELEMETRY_DISABLED=true
```

For the full event schema, property definitions, and configuration reference, see the [telemetry guide](docs/telemetry-guide.md).

---

## Multi-file support

Doc-Sentinel maps changed code files to their corresponding documentation using name-based matching. When a pull request touches multiple files, Doc-Sentinel audits all relevant documentation and posts one combined comment with a section for each file.

For example, a pull request that changes both `auth.py` and `api_client.py` finds and audits `authentication.md` and `api-reference.md` with no configuration.

When Doc-Sentinel finds no matching doc file, it falls back to `getting-started.md`.

---

## Historical audit CLI

The pull request bot catches drift going forward. The historical audit tells you how bad the existing damage is.

Run it once to get a full picture of your current documentation health across every `.md` file in your repository, scored and audited against its corresponding code.

#### Install the dependencies

```text
$ pip install PyGithub google-genai python-dotenv "posthog>=6.0.0"
```

#### Run an audit

To audit only the files that have matching code files:

```text
$ python historical_audit.py --repo OWNER/REPO
```

To audit every `.md` file in the repository:

```text
$ python historical_audit.py --repo OWNER/REPO --all
```

To save the report to a custom path:

```text
$ python historical_audit.py --repo OWNER/REPO --all --output my-report.md
```

#### Read the report

The Markdown report contains the following sections:

- A summary table of total files audited, accurate, outdated, and partial
- Each outdated file with its audit findings and suggested fixes
- Each healthy file with its AI readability score
- The average AI readability score across the repository

The command produces output in this form:

```text
Doc-Sentinel Historical Audit
Repository: your-org/your-repo
Mode: All .md files

Scanning repository...
Found 12 Markdown files and 8 code files.
Auditing: getting-started.md
  Status: ACCURATE | Score: 70%
Auditing: api-reference.md
  Status: OUTDATED | Score: 100%
Auditing: authentication.md
  Status: ACCURATE | Score: 90%

Files audited: 12
Requiring attention: 3
Healthy: 9
```

---

## Tech stack

- **Model orchestration:** Google Gemini 2.0 Flash.
- **System logic:** Python 3.10 or later.
- **Cloud infrastructure:** GitHub Actions.
- **Telemetry:** PostHog, anonymous and opt-in.
- **Governance:** Environment secret management for `GOOGLE_API_KEY`, `GITHUB_TOKEN`, and `POSTHOG_API_KEY`.

---

## How it works

Each run moves through 5 stages.

1. **Event trigger:** A developer opens a pull request, pushes a code change, or labels a Doc Detective test failure issue with `doc-detective`.
2. **File mapping:** Doc-Sentinel scans the repository for `.md` files and maps changed code files to their corresponding documentation using name-based matching.
3. **Drift analysis:** Gemini evaluates each code change against the matched documentation to detect technical drift.
4. **Intelligence scoring:** The `DocSentinelIntelligence` engine scores each doc file against the AI-Readability Style Guide.
5. **Remediation:** Doc-Sentinel posts one combined comment on the pull request with a section for each file, containing a severity label, an explanation, and a corrected Markdown snippet.

---

## Roadmap

- **Phase 1:** Automated detection and reporting. Complete.
- **Phase 2:** Multi-file audits, with recursive scanning across all `.md` files and automatic code-to-doc mapping. Complete.
- **Phase 2.5:** Doc Detective integration, which triggers a documentation audit when a Doc Detective test fails. Built in collaboration with [hawkeyexl](https://github.com/hawkeyexl). Complete.
- **Phase 2.75:** Historical audit CLI, which scans your entire repository for existing documentation drift in one command. Complete.
- **Phase 3:** Autonomous remediation, where the agent opens a pull request with corrected documentation for human review, validated by Doc Detective before merging.
- **Phase 3.5:** Self-instrumentation, with anonymous PostHog telemetry and a public dashboard of audit volume and drift rates. Complete.
- **Phase 4:** Stakeholder dashboard, which gives product managers and documentation leads strategic oversight.

---

## Quick start

To add Doc-Sentinel to a repository, complete the following 3 steps.

### 1. Add your secrets to GitHub

Go to your repository, then **Settings**, then **Secrets and variables**, then **Actions**, and add the following secrets:

- `GOOGLE_API_KEY`: Your Google Gemini API key from [Google AI Studio](https://aistudio.google.com).
- `GITHUB_TOKEN`: Provided automatically by GitHub Actions.
- `POSTHOG_API_KEY`: Optional. Leave it unset to disable telemetry entirely.
- `POSTHOG_HOST`: Optional. Set it to `https://us.i.posthog.com` for United States PostHog projects, or `https://eu.i.posthog.com` for European Union projects.

### 2. Add the workflow file

Create `.github/workflows/doc-audit.yml` in your repository and populate the file with the following code:

```yaml
name: Doc-Sentinel AI Audit
on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]
  issues:
    types: [ opened, labeled ]
jobs:
  audit-job:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
      issues: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 2
      - uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      - run: pip install PyGithub google-genai python-dotenv "posthog>=6.0.0" --upgrade
      - name: Run AI Audit
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
          REPO_NAME: ${{ github.repository }}
          PR_NUMBER: ${{ github.event.pull_request.number }}
          ISSUE_NUMBER: ${{ github.event.issue.number }}
          # Telemetry disables itself when POSTHOG_API_KEY is empty.
          POSTHOG_API_KEY: ${{ secrets.POSTHOG_API_KEY }}
          POSTHOG_HOST: ${{ secrets.POSTHOG_HOST }}
        run: python src/audit.py
```

Two details to note in this workflow:

- The `fetch-depth: 2` setting gives Doc-Sentinel access to the previous commit, which it needs to compute the diff.
- The `permissions` block grants write access to pull requests and issues so Doc-Sentinel can post its findings.

### 3. Open a pull request

Doc-Sentinel finds the relevant documentation files, audits all of them, and posts its findings as a single combined comment.

---

## Author

Reem Sabawi, Senior Technical Writer, Technical Educator, and AI-Native Builder.

[LinkedIn](https://www.linkedin.com/in/reem-s-78187b1b9/) | [Portfolio](https://reemsabawi-portfolio.notion.site/Reem-Sabawi-s-Professional-Portfolio-2fa1fb910d8180ce86b0ef3542ef9506) | [Landing page](https://reem-sab.github.io/doc-sentinel-ai/)
