# 🤖 Doc-Sentinel AI: Agentic Documentation Governance

**Doc-Sentinel AI** is a CI/CD-integrated tool that automatically audits your documentation on every code change, catching drift between your code and your docs before anything ships.

---

## 🎯 The Problem

Wrong documentation is more dangerous than no documentation.

When a developer follows outdated instructions with confidence and something breaks in production, that is not a people problem. It is a systems problem. Nobody flagged the drift. Nobody had a safety net.

Doc-Sentinel is that safety net. It hooks into your GitHub Actions pipeline, compares every code change against your documentation using AI, and posts its findings directly on the pull request — before anything merges.

---

## 🚀 Features

- **Drift Detection:** Compares every code change against your documentation using Gemini 2.0 Flash and flags anything that no longer matches — function signatures, parameters, renamed methods, removed steps.
- **Intelligence Scoring:** Scores your documentation for AI-Readability using the [AI-Readability Style Guide](./AI_STYLE_GUIDE.md) — catching vague pronouns, broken heading hierarchy, dense paragraphs, and missing code block metadata that cause context loss in RAG pipelines.
- **Actionable Remediation:** Posts severity labels, a one-sentence explanation of the drift, and a corrected Markdown snippet directly on the PR — ready to paste in.
- **Zero-Friction CI/CD:** Runs natively in GitHub Actions. No new tools, no new workflows.
- **Doc Detective Integration:** When Doc Detective test failures are detected, Doc Sentinel automatically wakes up, audits the affected file, and posts findings back on the issue. See [Phase 2.5](#️-roadmap).

---

## 🧠 The Two-Part Audit

Every Doc-Sentinel run performs two distinct checks:

**1. Drift Audit**
Gemini compares the code diff against the existing documentation to detect Technical Drift — changes to function signatures, parameters, renamed methods, or removed steps that are not reflected in the docs. If drift is found, the result starts with `YES` and a label of `Docs: Action Required` is applied.

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

## 🛠 Tech Stack

- **LLM Orchestration:** Google Gemini 2.0 Flash
- **System Logic:** Python 3.10+
- **Cloud Infrastructure:** GitHub Actions (CI/CD)
- **Governance:** Secure environment secret management (`GOOGLE_API_KEY`, `GITHUB_TOKEN`)

---

## 🧪 How It Works

1. **Event Trigger:** A developer opens a pull request, pushes a code change, or a Doc Detective test failure issue is labeled `doc-detective`.
2. **State Capture:** The agent fetches the latest `git diff` and corresponding documentation via the GitHub API.
3. **Drift Analysis:** Gemini evaluates the code change against the Markdown to detect Technical Drift.
4. **Intelligence Scoring:** The `DocSentinelIntelligence` engine scores the documentation against the AI-Readability Style Guide.
5. **Remediation:** Findings are posted directly on the PR or issue with a severity label, explanation, and corrected Markdown snippet.

---

## 🗺️ Roadmap

- **Phase 1: Automated Detection & Reporting** ✅ Complete
- **Phase 2: Multi-File Audits** — Recursive scanning across entire `/docs` directories.
- **Phase 2.5: Doc Detective Integration** ✅ Complete — When Doc Detective test failures are detected, Doc Sentinel automatically triggers a documentation audit. Built in collaboration with [@hawkeyexl](https://github.com/hawkeyexl).
- **Phase 3: Autonomous Remediation** — Agent opens a PR with corrected documentation for human review, validated by Doc Detective before merging.
- **Phase 4: Stakeholder Dashboard** — Strategic oversight for Product Managers and Documentation Leads.

---

## ⚡ Quick Start

### 1. Add your secrets to GitHub

Go to your repo → Settings → Secrets and variables → Actions and add:
- `GOOGLE_API_KEY` — your Google Gemini API key from [Google AI Studio](https://aistudio.google.com)
- `GITHUB_TOKEN` — automatically provided by GitHub Actions

### 2. Add the workflow file

Create `.github/workflows/doc-audit.yml` in your repo:

```yaml
name: AI Documentation Audit
on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]
  issues:
    types: [ opened, labeled ]
jobs:
  audit:
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

Open a pull request and Doc-Sentinel will automatically audit your docs and post its findings as a comment.

---

## 👤 Author

**Reem Sabawi**
*Senior Technical Writer | Technical Educator | AI-Native Builder*

[LinkedIn](https://www.linkedin.com/in/reem-s-78187b1b9/) | [Portfolio](https://reemsabawi-portfolio.notion.site/Reem-Sabawi-s-Professional-Portfolio-2fa1fb910d8180ce86b0ef3542ef9506)
