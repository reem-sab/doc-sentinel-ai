# 🤖 Doc-Sentinel AI: Agentic Documentation Governance

**Doc-Sentinel AI** is a CI/CD-integrated tool that automatically audits your documentation on every code change, catching drift between your code and your docs before anything ships.

Built by a Senior Technical Writer who got tired of waiting for someone else to solve documentation debt.

🌐 **[doc-sentinel-ai.github.io](https://reem-sab.github.io/doc-sentinel-ai/)** — Live demo and landing page

---

## 🎯 The Problem

Wrong documentation is more dangerous than no documentation.

When a developer follows outdated instructions with confidence and something breaks in production, that is not a people problem. It is a systems problem. Nobody flagged the drift. Nobody had a safety net.

Doc-Sentinel is that safety net. It hooks into your GitHub Actions pipeline, compares every code change against your documentation using AI, and posts its findings directly on the pull request — before anything merges.

---

## 🚀 Features

- **Multi-File Drift Detection:** Automatically identifies which documentation files are affected by each code change and audits all of them in a single PR comment.
- **Semantic Integrity Audits:** Uses Gemini 2.0 Flash to understand the *intent* of code changes, catching logic shifts that regex-based linters miss.
- **Intelligence Scoring:** Scores your documentation for AI-Readability using the [AI-Readability Style Guide](./AI_STYLE_GUIDE.md) — catching vague pronouns, broken heading hierarchy, dense paragraphs, and missing code block metadata.
- **Actionable Remediation:** Posts severity labels, a one-sentence explanation, and a corrected Markdown snippet directly on the PR — ready to paste in.
- **Zero-Friction CI/CD:** Runs natively in GitHub Actions. No new tools, no new workflows.
- **Doc Detective Integration:** When Doc Detective test failures are detected, Doc Sentinel automatically wakes up, audits the affected file, and posts findings back on the issue.

---

## 🧠 The Two-Part Audit

Every Doc-Sentinel run performs two distinct checks:

**1. Drift Audit**
Gemini compares the code diff against the existing documentation to detect Technical Drift — changes to function signatures, parameters, renamed methods, or removed steps that are not reflected in the docs. If drift is found, the result starts with `YES` and a `Docs: Action Required` label is applied.

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

## 🔍 Multi-File Support

Doc-Sentinel automatically maps changed code files to their corresponding documentation using name-based matching. When a PR touches multiple files, Doc-Sentinel audits all relevant documentation and posts one combined comment with a section per file.

For example, a PR that changes both `auth.py` and `api_client.py` will automatically find and audit `authentication.md` and `api-reference.md` — no configuration needed.

If no matching doc file is found, Doc-Sentinel falls back to `getting-started.md`.

---

## 🛠 Tech Stack

- **LLM Orchestration:** Google Gemini 2.0 Flash
- **System Logic:** Python 3.10+
- **Cloud Infrastructure:** GitHub Actions (CI/CD)
- **Governance:** Secure environment secret management (`GOOGLE_API_KEY`, `GITHUB_TOKEN`)

---

## 🧪 How It Works

1. **Event Trigger:** A developer opens a pull request, pushes a code change, or a Doc Detective test failure issue is labeled `doc-detective`.
2. **File Mapping:** Doc-Sentinel scans the repo for `.md` files and maps changed code files to their corresponding documentation using name-based matching.
3. **Drift Analysis:** Gemini evaluates each code change against the matched documentation to detect Technical Drift.
4. **Intelligence Scoring:** The `DocSentinelIntelligence` engine scores each doc file against the AI-Readability Style Guide.
5. **Remediation:** One combined comment is posted on the PR with a section per file — severity label, explanation, and corrected Markdown snippet.

---

## 🗺️ Roadmap

- **Phase 1: Automated Detection & Reporting** ✅ Complete
- **Phase 2: Multi-File Audits** ✅ Complete — Recursive scanning across all `.md` files with automatic code-to-doc mapping.
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

Open a pull request and Doc-Sentinel will automatically find the relevant documentation files, audit them all, and post its findings as a single combined comment.

---

## 👤 Author

**Reem Sabawi**
*Senior Technical Writer | Technical Educator | AI-Native Builder*

[LinkedIn](https://www.linkedin.com/in/reem-s-78187b1b9/) | [Portfolio](https://reemsabawi-portfolio.notion.site/Reem-Sabawi-s-Professional-Portfolio-2fa1fb910d8180ce86b0ef3542ef9506) | [Landing Page](https://reem-sab.github.io/doc-sentinel-ai/)
