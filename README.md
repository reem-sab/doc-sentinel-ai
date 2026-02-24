# 🤖 Doc-Sentinel AI: Agentic Documentation Governance

**Doc-Sentinel AI** is a CI/CD-integrated solution designed to eliminate **Documentation Debt**—the widening gap between rapid code deployment and accurate technical content. By leveraging **Google Gemini 2.0 Flash** and **GitHub Actions**, it provides a scalable "safety net" for technical accuracy in high-velocity development environments.



---

## 🎯 The Product Vision
In complex cloud ecosystems (like AWS Greengrass), a single casing error in a parameter (e.g., `DeviceID` vs `deviceid`) can break a customer's production environment. **Doc-Sentinel** acts as a "First Responder" for technical truth, ensuring that every code push is automatically reconciled with its documentation to reduce support overhead and improve **Developer Experience (DX)**.

---

## 🚀 Strategic Features
* **Semantic Integrity Audits:** Uses LLM orchestration to understand the *intent* of code changes, identifying logic shifts that traditional regex-based linters miss.
* **Zero-Friction CI/CD:** Operates natively within the **SDLC** via GitHub Actions, ensuring governance doesn't slow down the release cycle.
* **Risk-Based Reporting:** Flags "Critical" discrepancies in parameters and function signatures, prioritizing documentation that impacts system stability.
* **Agentic Perception:** Autonomously observes code diffs, reasons through technical impact, and generates precise remediation steps without human prompting.

---
🤖 AI-Readability & Optimization (The "Intelligence" Layer)
Modern documentation is read by AI just as much as by humans. Doc-Sentinel AI now scans your docs to ensure they are optimized for LLM Context Windows and RAG (Retrieval-Augmented Generation).

Ambiguity Detection: Flags vague pronouns (e.g., "it," "this," "there") that cause "context drift" in AI embeddings.

Semantic Hierarchy Audit: Ensures your Markdown structure allows for clean semantic chunking.

Context Injection Suggestions: Recommends adding metadata or YAML frontmatter to help AI crawlers categorize your content.

LLMS.txt Generation: Automatically suggests a high-level summary file for your project root to act as an AI entry point.

---

## 🛠 Tech Stack
* **LLM Orchestration:** Google Gemini 2.0 Flash (Optimized for 1M+ token context windows)
* **System Logic:** Python 3.10 & PyGithub
* **Cloud Infrastructure:** GitHub Actions (CI/CD)
* **Governance:** Secure environment secret management for API authentication

---

## 🧪 The Governance Workflow
1.  **Event Trigger:** A developer pushes a code change (e.g., updating a function signature or parameter casing).
2.  **State Capture:** The agent fetches the latest `git diff` and corresponding documentation via the GitHub API.
3.  **Cross-Functional Analysis:** Gemini 2.0 evaluates the code change against the Markdown to detect "Technical Drift." 
4.  **Strategic Remediation:** If a mismatch is found, the agent logs a ready-to-use update, reducing the time-to-fix from hours to seconds.



---

## 🗺️ Roadmap: Scaling the Impact
* [x] **Phase 1: Automated Detection & Reporting** (Current MVP)
* [ ] **Phase 2: Global Repository Health** (Support for multi-file audits and recursive scanning)
* [ ] **Phase 3: Autonomous Remediation** (Agent opens a PR with corrected documentation for human review)
* [ ] **Phase 4: Stakeholder Dashboard** (Strategic oversight for Product Managers and Documentation Leads)

---

## 👤 Author
**Reem Sabawi** *Senior Technical Writer | Technical Writing Educator | Aspiring Product Manager* [LinkedIn](https://www.linkedin.com/in/reem-s-78187b1b9/) | [Portfolio](https://reemsabawi-portfolio.notion.site/Reem-Sabawi-s-Professional-Portfolio-2fa1fb910d8180ce86b0ef3542ef9506)

### `initialize_user_session`
| Parameter | Type | Description |
| :--- | :--- | :--- |
| `user_id` | String | The unique identifier for the user. |
| `session_timeout` | Integer | The time in milliseconds before session expires. |