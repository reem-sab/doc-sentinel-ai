# 🤖 Doc-Sentinel AI: Automated Documentation Auditor

**Doc-Sentinel AI** is a CI/CD-integrated tool that ensures your technical documentation never falls behind your code. By leveraging **Google Gemini 2.0 Flash** and **GitHub Actions**, it automatically audits code changes (diffs) against existing Markdown files to detect "Doc Debt."

---

## 🚀 Key Features
- **Semantic Audit:** Uses Generative AI to understand the *intent* of code changes, not just keyword matching.
- **Automated CI/CD:** Runs on every `push` or `pull_request` via GitHub Actions.
- **Context-Aware Suggestions:** Provides ready-to-paste Markdown updates when it detects outdated documentation.
- **Scalable Infrastructure:** Built with a "Docs-as-Code" philosophy, easily adaptable for large-scale documentation sites (Docusaurus, Sphinx, etc.).

---

## 🛠 Tech Stack
- **Language:** Python 3.10
- **AI Brain:** Google Gemini 2.0 Flash (Generative AI SDK)
- **Automation:** GitHub Actions (CI/CD)
- **API Integration:** PyGithub (GitHub REST API)
- **Security:** GitHub Secrets for encrypted API management

---

## 📂 Project Structure
- `audit.py`: The core logic that retrieves GitHub data and communicates with Gemini.
- `getting-started.md`: A sample documentation file used for auditing.
- `.github/workflows/doc-audit.yml`: The automation "recipe" that runs the auditor in the cloud.

---

## 🧪 How It Works (The Audit Flow)
1. **Developer Pushes Code:** A code change is pushed to the repository.
2. **GitHub Action Triggers:** A virtual environment is spun up, installing necessary dependencies.
3. **AI Analysis:** The script sends the `git diff` and the current `getting-started.md` to Gemini 2.0.
4. **Report Generation:** The AI evaluates if the documentation still matches the code. If not, it prints a suggested rewrite in the workflow logs.



---

## 📈 Future Roadmap
- [ ] Support for multiple documentation files and folders.
- [ ] Automatic Pull Request comments with suggested doc fixes.
- [ ] Integration with Slack/Discord for team notifications.

---

## 👤 Author
**Reem Sabawi** *Senior Technical Writer | Technical Writing Educator* [LinkedIn](https://www.linkedin.com/in/reem-s-78187b1b9/) | [Portfolio](https://reemsabawi-portfolio.notion.site/Reem-Sabawi-s-Professional-Portfolio-2fa1fb910d8180ce86b0ef3542ef9506)
