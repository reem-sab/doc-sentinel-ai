# 🤖 Doc-Sentinel AI: Agentic Documentation Auditor

**Doc-Sentinel AI** is a CI/CD-integrated agent that ensures technical documentation never falls behind the source code. By leveraging **Google Gemini 2.0 Flash** and **GitHub Actions**, it automatically detects "Documentation Drift" and suggests precise updates.

---

## 🚀 Key Features
- **Semantic Analysis:** Uses Gemini 2.0 to understand the *intent* of code changes (diffs), not just keyword matching.
- **CI/CD Integration:** Runs autonomously on every `push` or `pull_request` via GitHub Actions.
- **Context-Aware Recommendations:** Generates ready-to-use Markdown updates when discrepancies are found.
- **Agentic Design:** Operates as a "Knowledge Agent" that observes, reasons, and reports findings without human intervention.

---

## 🛠 Tech Stack
- **AI Brain:** Google Gemini 2.0 Flash (Generative AI SDK)
- **Language:** Python 3.10
- **Automation:** GitHub Actions (CI/CD)
- **API Integration:** PyGithub (GitHub REST API)
- **Environment:** Secure secrets management for API authentication

---

## 📂 Project Structure
- `audit.py`: The core AI agent logic for data retrieval and analysis.
- `.github/workflows/doc-audit.yml`: The automation recipe for cloud execution.
- `getting-started.md`: Target documentation for real-time auditing.

---

## 🧪 The Audit Workflow
1. **Trigger:** A developer pushes a code change to the repository.
2. **Perception:** The agent uses the GitHub API to fetch the latest `git diff` and the corresponding documentation.
3. **Reasoning:** Gemini 2.0 evaluates the code change against the text. 
4. **Action:** If the docs are outdated, the agent logs a concise, updated version of the Markdown in the CI/CD dashboard.



---

## 🗺️ Roadmap: The Agentic Evolution
To maintain professional risk management, this project follows a phased rollout:

- [x] **Phase 1:** Automated detection and reporting (Current).
- [ ] **Phase 2:** Support for multi-file audits and recursive directory scanning.
- [ ] **Phase 3 (High Impact):** **Auto-Fix Mode.** Enable the agent to automatically open a Pull Request with the corrected documentation for human review.
- [ ] **Phase 4:** Real-time team notifications via Slack/Teams.

---

## 👤 Author
**Reem Sabawi** *Senior Technical Writer | Technical Writing Educator* [LinkedIn](https://www.linkedin.com/in/reem-s-78187b1b9/) | [Portfolio](https://reemsabawi-portfolio.notion.site/Reem-Sabawi-s-Professional-Portfolio-2fa1fb910d8180ce86b0ef3542ef9506)
