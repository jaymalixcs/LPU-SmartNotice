# ⚡ LPU SmartNotice — 15-Minute Emergency Revision Cheat Sheet
*Keep this open or printed before entering your viva room!*

---

## 🎯 1. The Core Pitch (Say This in First 30 Seconds)
> "LPU SmartNotice is a **Grounded RAG (Retrieval-Augmented Generation) & Personalization Platform** for university announcements. It solves university information overload (over 7,000 notices/year) by:
> 1. Structuring unstructured notice text into Pydantic models via Google Gemini API.
> 2. Personalizing notice feeds using an explainable 5-factor mathematical formula.
> 3. Answering student questions with exact source citations (Title & Reference #) using a hybrid ChromaDB vector + lexical search pipeline."

---

## 🧱 2. Key Architecture Numbers to Memorize
* **Historical Dataset:** 7,350 announcements (`data/all_announcements_with_attachment_flag.json`)
* **Live Synced Notices:** 94 announcements (`storage/smartnotice.db` -> `live_announcements`)
* **Total Corpus:** 7,444 announcements
* **ChromaDB Collection:** `lpu_announcements`, **400 embedded records**, dimension = **768**
* **Embedding Model:** `gemini-embedding-2` (Google Cloud GenAI SDK)
* **Generation Model:** `gemini-flash-lite-latest` (with multi-model failover to `gemini-3.5-flash`)
* **Test Suite:** **81 tests passed, 0 failed** in `pytest`

---

## 🧮 3. The Personalization Formula
$$\text{Score} = (0.25 \times \text{Year}) + (0.20 \times \text{Department}) + (0.25 \times \text{Interests}) + (0.15 \times \text{Urgency}) + (0.15 \times \text{Global Importance})$$
* **Range:** $0.0$ to $1.0$.
* If student's year matches: $1.0$; if excluded/mismatched: $0.1$.
* Explainable and transparent — not an opaque black-box neural net.

---

## 🔍 4. The Hybrid RAG Pipeline (Step-by-Step)
```text
Student Question
      │
      ▼
1. Typo Normalization ("accoummodation" -> "accommodation") & Concept Cluster Expansion
      │
      ├──────────────────────────────┬──────────────────────────────┐
      ▼                              ▼                              ▼
ChromaDB Vector Search        Lexical Scoring             Reference # Match
(768-dim Cosine Similarity)   (BM25 Term Frequency)       (+15 point boost)
      │                              │                              │
      └──────────────────────────────┴──────────────────────────────┘
                                     │
                                     ▼
                Reciprocal Rank Fusion (RRF with k=60)
                                     │
                                     ▼
                  Strictly Grounded Prompt Construction
           (Includes calendar context: Today/Tomorrow ISO dates)
                                     │
                                     ▼
                 Google Gemini API (gemini-flash-lite-latest)
                                     │
                                     ▼
     Response with Verifiable Source Citations: [Source ID: ANN-...]
```

---

## 🛡️ 5. Top 5 Killer Examiner Questions & Exact Spoken Answers

### Q1: "Why did you use RAG instead of fine-tuning Gemini?"
> **Spoken Answer:** "Fine-tuning updates model weights, which is expensive and freezes knowledge at a single point in time. University notices change every few hours. RAG keeps the model pretrained and fetches live announcements directly from our database at query time. This eliminates retraining costs, guarantees real-time accuracy, and allows us to provide exact source citations."

### Q2: "What is ChromaDB and why do you also need SQLite?"
> **Spoken Answer:** "ChromaDB is a **vector database** that performs approximate nearest neighbor search over 768-dimensional semantic embeddings. SQLite is a **relational database** providing ACID transactions for structured student profiles, timetables, and exact primary key lookups. You cannot replace SQLite with ChromaDB because vector databases cannot efficiently handle relational joins, timetable queries, or transactional updates."

### Q3: "What happens if a notice mentions an attachment that isn't in your database?"
> **Spoken Answer:** "We implemented an `EvidenceCompleteness` flag. When a notice references an external PDF or spreadsheet that is unavailable, the status is marked as `ATTACHMENT_MISSING`. Our system prompt strictly forbids the LLM from fabricating attachment contents and forces it to warn the student to check UMS directly."

### Q4: "What is the difference between Publication Date and Deadline?"
> **Spoken Answer:** "The **Publication Date** is when the university issued the notice (e.g., 22 October 2026). The **Action Deadline** is the due date by which students must complete the task (e.g., 26 October 2026). In our RAG prompt and temporal service, we explicitly extract both dates so the model never confuses when a notice was uploaded with when the action is due."

### Q5: "What are your project's limitations?"
> **Spoken Answer:** "Three main limitations:
> 1. We detect attachments and warn the user, but do not yet perform OCR on binary PDF files.
> 2. The Google Gemini free tier limits embeddings to 1,000 requests/day, which we mitigate using an offline pseudo-embedding fallback and lexical search.
> 3. Personalization currently uses an explainable weighted formula rather than supervised machine learning trained on implicit click logs."

---

## 🏃 6. Emergency 30-Second Reset (If Server / Demo Fails)
1. Run backend command:
   ```powershell
   .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
2. Open in browser: `http://localhost:8000`
3. Swagger Docs: `http://localhost:8000/docs`
4. Health check: `http://localhost:8000/api/v1/health`

