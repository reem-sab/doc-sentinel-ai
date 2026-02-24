# 🤖 Doc-Sentinel AI: Agentic Documentation Governance

**Doc-Sentinel AI** is a CI/CD-integrated solution designed to eliminate **Documentation Debt**—the gap between rapid code deployment and accurate technical content—while optimizing for **AI Crawlability**. By leveraging **Google Gemini 2.0 Flash** and **GitHub Actions**, it provides a scalable "safety net" ensuring every code push is accurate for humans and high-performance for AI-driven RAG (Retrieval-Augmented Generation) systems.



---

## 🎯 The Dual Vision
In modern development ecosystems, documentation serves two masters: the **Developer** and the **AI Agent**. **Doc-Sentinel** acts as a "First Responder" for technical truth, reconciling code diffs with documentation while ensuring the content structure is optimized for machine consumption.

* **Documentation Debt Resolution:** Automatically reconciles code shifts (like parameter casing or function signatures) with their documentation to improve **Developer Experience (DX)**.
* **AI-Readability Optimization:** Eliminates "context drift" and structural gaps, ensuring your docs are ready for LLM context windows and semantic search.

---

## 🚀 Strategic Features
* **Semantic Integrity Audits:** Uses LLM orchestration to identify logic shifts and documentation mismatches that traditional regex-based linters miss.
* **AI-Readability Scoring:** Generates a **0-100% grade** for documentation based on its suitability for AI-driven retrieval systems.
* **Ambiguity Detection:** Flags vague pronouns (e.g., "it," "this," "there") at the start of sections to prevent context loss during AI chunking.
* **Agentic Perception:** Autonomously observes code diffs, calculates readability impact, and generates precise remediation suggestions.

---

## 📊 The "Sentinel" Grading System
The Intelligence Layer evaluates content across three key metrics to ensure it is both accurate and crawlable. For detailed writing standards, see the [AI-Readability Style Guide](./AI_STYLE_GUIDE.md).

| Metric | Weight | Audit Focus |
| :--- | :--- | :--- |
| **Context Clarity** | 40% | Resolving ambiguous subjects for AI retrievers and human readers. |
| **Structural Health** | 30% | Enforcing H1 > H2 hierarchy to solve doc debt and improve chunking. |
| **Conciseness** | 30% | Managing paragraph length to prevent context loss in RAG pipelines. |

---

## 🛠 Tech Stack
* **LLM Orchestration:** Google Gemini 2.0 Flash (Optimized for rapid analysis and large context windows).
* **System Logic:** Python 3.10+
* **Cloud Infrastructure:** GitHub Actions (CI/CD).
* **Governance:** Secure environment secret management for API authentication (`GOOGLE_API_KEY`).

---

## 🧪 The Governance Workflow
1.  **Event Trigger:** A developer pushes code or documentation updates.
2.  **State Capture:** The agent fetches the latest `git diff` and Markdown content via the GitHub API.
3.  **Cross-Functional Analysis:** Gemini evaluates "Technical Drift" (Debt) and content "Crawlability" (Intelligence).
4.  **Strategic Remediation:** The agent generates a dashboard report with a percentage score and actionable suggestions directly in the GitHub Actions summary.

---

## 👤 Author
**Reem Sabawi**
*Senior Technical Writer | Technical Educator | AI-Native Builder*
[LinkedIn](https://www.linkedin.com/in/reem-s-78187b1b9/) | [Portfolio](https://reemsabawi-portfolio.notion.site/Reem-Sabawi-s-Professional-Portfolio-2fa1fb910d8180ce86b0ef3542ef9506)


