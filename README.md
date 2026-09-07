# 🤖 Doc-Sentinel AI: Agentic Documentation Governance

**Doc-Sentinel AI** is a CI/CD-integrated tool that automatically audits your documentation on every code change, catching drift between your code and your docs before anything ships.

Built by a Senior Technical Writer who got tired of waiting for someone else to solve documentation debt.

🌐 Live demo and landing page: **[reem-sab.github.io/doc-sentinel-ai](https://reem-sab.github.io/doc-sentinel-ai/)**

---

## 🎯 The problem

Wrong documentation is more dangerous than no documentation.

When a developer follows outdated instructions with confidence and something breaks in production, that is not a people problem. It is a systems problem. Nobody flagged the drift. Nobody had a safety net.

Doc-Sentinel is that safety net. It hooks into your GitHub Actions pipeline, compares every code change against your documentation using AI, and posts its findings directly on the pull request, before anything merges.

---

## 🚀 Features

- **Multi-File Drift Detection:** Automatically identifies which documentation files are affected by each code change and audits all of them in a single PR comment.
- **Historical Audit CLI:** Scan your entire repository for existing documentation drift in one command. Get a full health report across every `.md` file, not just what changes going forward.
- **Semantic Integrity Audits:** Uses Gemini 2.0 Flash to understand the **intent** of code changes, catching logic shifts that regex-based linters miss.
- **Intelligence Scoring:** Scores your documentation for AI-Readability using the [AI-Readability Style Guide](./AI_STYLE_GUIDE.md), catching vague pronouns, broken heading hierarchy, dense paragraphs, and missing code block metadata.
- **Actionable Remediation:** Posts severity labels, a one-sentence explanation, and a corrected Markdown snippet directly on the PR, ready to paste in.
- **Zero-Friction CI/CD:** Runs natively in GitHub Actions. No new tools, no new workflows.
- **Doc Detective Integration:** When Doc Detective test failures are detected, Doc-Sentinel automatically wakes up, audits the affected file, and posts findings back on the issue.
- **Product Analytics:** PostHog (self-reported usage and audit outcomes)

---

## 🧠 The two-part audit

Every Doc-Sentinel run performs two distinct checks:

**1. Drift Audit**
Gemini compares the code diff against the existing documentation to detect technical drift: changes to function signatures, parameters, renamed methods, or removed steps that are not reflected in the docs. If drift is found, the result starts with `YES` and a `Docs: Action Required` label is applied.

**2. Intelligence Audit**
The `DocSentinelIntelligence` engine scores the documentation for AI-Readability using the standards defined in the [AI-Readability Style Guide](./AI_STYLE_GUIDE.md). It checks for:

| Rule | What It Catches |
| :--- | :--- |
| **Context Persistence** | Vague pronouns (It, This, They) at the start of paragraphs that cause AI chunking failures |
| **Semantic Hierarchy** | Skipped heading levels that break AI crawlers' understanding of document structure |
| **Paragraph Density** | Walls of text that cause information dilution in RAG embeddings |
| **Code Block Metadata** | Unlabeled code blocks that prevent AI agents from identifying language and context |
| **Visual-to-Text Bridging** | Images without alt-text that are invisible to text-only RAG pipelines |

The result is a **0–100% AI-Readability Score** posted on every PR alongside the drift findings.

---

## 📈 Measuring Itself

[#-measuring-itself](#-measuring-itself)

Doc-Sentinel tracks its own behavior with PostHog, because a tool that
audits documentation quality should be able to show its own evidence.

📊 **[Live public dashboard](https://us.posthog.com/shared/fudAKtSiK2nY9RmXk1z_mqSjYE-2Gg)**

| Event | Fires when | Key properties |
| ----- | ---------- | -------------- |
| `audit_started` | A PR, push, or labeled issue triggers a run | `trigger_type`, `files_matched` |
| `drift_detected` | Gemini returns `YES` on the Drift Audit | `severity`, `doc_file` |
| `audit_clean` | The Drift Audit finds no technical drift | `doc_file` |
| `readability_scored` | The Intelligence engine finishes scoring | `score`, `rules_failed` |
| `remediation_posted` | A corrected snippet is posted on the PR | `doc_file` |
| `historical_audit_run` | The CLI scans a full repository | `mode`, `files_audited` |

No documentation content, code, repository names, or diffs are ever sent.
Events carry counts, scores, and rule names only.

### Opting out

[#opting-out](#opting-out)

Set the following in your workflow to disable analytics entirely:



## 🔍 Multi-file support

Doc-Sentinel automatically maps changed code files to their corresponding documentation using name-based matching. When a PR touches multiple files, Doc-Sentinel audits all relevant documentation and posts one combined comment with a section per file.

For example, a PR that changes both `auth.py` and `api_client.py` automatically finds and audits `authentication.md` and `api-reference.md`, with no configuration needed.

If no matching doc file is found, Doc-Sentinel falls back to `getting-started.md`.

---

## 🕵️ Historical audit CLI

The PR bot catches drift going forward. The Historical Audit tells you how bad the damage already is.

Run it once to get a full picture of your existing documentation health across every `.md` file in your repo, scored and audited against its corresponding code.

### Installation

```bash
pip install PyGithub google-genai python-dotenv
```

### Usage

```bash
# Audit only files with matching code files
python historical_audit.py --repo OWNER/REPO

# Audit every .md file in the repo
python historical_audit.py --repo OWNER/REPO --all

# Save report to a custom path
python historical_audit.py --repo OWNER/REPO --all --output my-report.md
```

### What you get

A full Markdown report with:
- **Summary table**: total files audited, accurate, outdated, and partial
- **Files requiring attention**: each outdated file with its audit findings and suggested fixes
- **Files in good shape**: listed with their AI-Readability scores
- **Average AI-Readability Score**: computed across the entire repo

### Example output

```
🛡️  Doc-Sentinel Historical Audit
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

## 🛠 Tech stack

- **LLM Orchestration:** Google Gemini 2.0 Flash
- **System Logic:** Python 3.10+
- **Cloud Infrastructure:** GitHub Actions (CI/CD)
- **Governance:** Secure environment secret management (`GOOGLE_API_KEY`, `GITHUB_TOKEN`)

---

## 🧪 How it works

1. **Event Trigger:** A developer opens a pull request, pushes a code change, or a Doc Detective test failure issue is labeled `doc-detective`.
2. **File Mapping:** Doc-Sentinel scans the repo for `.md` files and maps changed code files to their corresponding documentation using name-based matching.
3. **Drift Analysis:** Gemini evaluates each code change against the matched documentation to detect technical drift.
4. **Intelligence Scoring:** The `DocSentinelIntelligence` engine scores each doc file against the AI-Readability Style Guide.
5. **Remediation:** Doc-Sentinel posts one combined comment on the PR with a section per file, containing a severity label, explanation, and corrected Markdown snippet.

---

## 🗺️ Roadmap

- **Phase 1: Automated Detection and Reporting** ✅ Complete
- **Phase 2: Multi-File Audits** ✅ Complete. Recursive scanning across all `.md` files with automatic code-to-doc mapping.
- **Phase 2.5: Doc Detective Integration** ✅ Complete. When Doc Detective test failures are detected, Doc-Sentinel automatically triggers a documentation audit. Built in collaboration with [@hawkeyexl](https://github.com/hawkeyexl).
- **Phase 2.75: Historical Audit CLI** ✅ Complete. Scan your entire repo for existing documentation drift in one command.
- **Phase 3: Autonomous Remediation:** Agent opens a PR with corrected documentation for human review, validated by Doc Detective before merging.
- **Phase 3.5: Self-Instrumentation** ✅ Complete — PostHog analytics on every audit run, with a public dashboard of drift rates and AI-Readability score distribution.

---

## ⚡ Quick start

### 1. Add your secrets to GitHub

Go to your repo → Settings → Secrets and variables → Actions and add:
- `GOOGLE_API_KEY`: your Google Gemini API key from [Google AI Studio](https://aistudio.google.com)
- `GITHUB_TOKEN`: automatically provided by GitHub Actions

### 2. Add the workflow file

Create `.github/workflows/doc-audit.yml` in your repo:

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
      - run: pip install PyGithub google-genai python-dotenv
      - name: Run AI Audit
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
          REPO_NAME: ${{ github.repository }}
          PR_NUMBER: ${{ github.event.pull_request.number }}
          ISSUE_NUMBER: ${{ github.event.issue.number }}
        run: python src/audit.py
```

### 3. That's it

Open a pull request and Doc-Sentinel automatically finds the relevant documentation files, audits them all, and posts its findings as a single combined comment.

---

## 👤 Author

**Reem Sabawi**
*Senior Technical Writer | Technical Educator | AI-Native Builder*

[LinkedIn](https://www.linkedin.com/in/reem-s-78187b1b9/) | [Portfolio](https://reemsabawi-portfolio.notion.site/Reem-Sabawi-s-Professional-Portfolio-2fa1fb910d8180ce86b0ef3542ef9506) | [Landing Page](https://reem-sab.github.io/doc-sentinel-ai/)
