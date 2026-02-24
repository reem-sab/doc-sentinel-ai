# 📖 AI-Readability Style Guide

This guide outlines the standards used by **Doc-Sentinel AI** to score documentation for "Crawlability" and "AI-Friendliness." Following these rules ensures that RAG systems and LLMs can accurately retrieve and synthesize your content.

---

## 1. Context Persistence (The "No-It" Rule)
AI models process information in "chunks." If a chunk starts with a vague pronoun, the AI loses the subject.

* **❌ Poor:** "It is used to authenticate users. This ensures the session is secure."
* **✅ Better:** "The **Auth-Service SDK** is used to authenticate users. This **verification step** ensures the session is secure."
* **Guideline:** Always re-establish the subject at the start of a new paragraph or H2/H3 section.

## 2. Semantic Hierarchy
AI crawlers use Markdown headers to understand the relationship between ideas.

* **Rule:** Never skip header levels (e.g., don't jump from # H1 to ### H3).
* **Rule:** Use descriptive headers. Instead of `## Setup`, use `## Setup for Python SDK`.

## 3. Paragraph Density & "Chunkability"
Large walls of text increase the risk of "information dilution" when an AI creates embeddings.

* **Guideline:** Keep paragraphs under 150 words.
* **Guideline:** Use bulleted lists for technical parameters or step-by-step instructions to create clear "semantic breaks."

## 4. Code Block Metadata
AI agents need to know what they are looking at to provide accurate snippets.

* **❌ Poor:** ```
    docker run sentinel
    ```
* **✅ Better:**
    ```bash
    # Run the Doc-Sentinel audit container
    docker run sentinel
    ```

## 5. Visual-to-Text Bridging
Since many RAG pipelines are text-only, images must be "described" for the machine.

* **Requirement:** All images must have descriptive Alt-Text.
* **Requirement:** If a diagram is complex, provide a short 1-sentence summary immediately below the image.

---
*Score your docs now by running `python src/audit.py`!*
