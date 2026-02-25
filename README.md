# 🤖 Doc-Sentinel AI: Agentic Documentation Governance

**Doc-Sentinel AI** is a CI/CD-integrated tool that automatically audits your documentation on every code change, catching drift between your code and your docs before anything ships.

Built by a Senior Technical Writer who got tired of waiting for someone else to solve documentation debt.

---

## 🎯 The Problem

Wrong documentation is more dangerous than no documentation.

When a developer follows outdated instructions with confidence and something breaks in production, that is not a people problem. It is a systems problem. Nobody flagged the drift. Nobody had a safety net.

Doc-Sentinel is that safety net. It hooks into your GitHub Actions pipeline, compares every code change against your documentation using AI, and posts its findings directly on the pull request — before anything merges.

---

## 🚀 Features

- **Semantic Integrity Audits:** Uses LLM orchestration to understand the *intent* of code changes, catching logic shifts that regex-based linters miss.
- **Severity Labels:** Flags discrepancies as Critical or Minor so teams can prioritize what to fix first.
- **Zero-Friction CI/CD:** Runs natively in GitHub Actions. No new tools, no new workflows.
- **PR Comments:** Posts audit results directly on the pull request with a corrected Markdown snippet ready to paste in.
- **Agentic Perception:** Autonomously observes code diffs, reasons through technical impact, and generates precise remediation steps.

---

## 🛠 Tech Stack

- **LLM Orchestration:** Google Gemini 2.0 Flash
- **System Logic:** Python 3.10+
- **Cloud Infrastructure:** GitHub Actions (CI/CD)
- **Governance:** Secure environment secret management (`GOOGLE_API_KEY`, `GITHUB_TOKEN`)

---

## 🧪 How It Works

1. **Event Trigger:** A developer opens a pull request or pushes a code change.
2. **State Capture:** The agent fetches the latest `git diff` and corresponding documentation via the GitHub API.
3. **AI Analysis:** Gemini evaluates the code change against the Markdown to detect Technical Drift.
4. **Remediation:** If drift is found, the agent posts a severity label, a one-sentence explanation, and a corrected Markdown snippet directly on the PR.

---

## 🗺️ Roadmap

- **Phase 1: Automated Detection & Reporting** ✅ Current MVP
- **Phase 2: Multi-File Audits** — Support for recursive scanning across entire `/docs` directories.
- **Phase 2.5: Doc Detective Integration** — When Doc Detective test failures are detected, Doc Sentinel automatically triggers a documentation audit. Built in collaboration with [@hawkeyexl](https://github.com/hawkeyexl).
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
jobs:
  audit:
    runs-on: ubuntu-latest
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
        run: python audit.py
```

### 3. That's it

Open a pull request and Doc-Sentinel will automatically audit your docs and post its findings as a comment.

---

## 👤 Author

**Reem Sabawi**
*Senior Technical Writer | Technical Educator | AI-Native Builder*

[LinkedIn](https://www.linkedin.com/in/reem-s-78187b1b9/) | [Portfolio](https://reemsabawi-portfolio.notion.site/Reem-Sabawi-s-Professional-Portfolio-2fa1fb910d8180ce86b0ef3542ef9506)
