# 🎬 LPU SmartNotice — 5-Minute Practical Viva Demo Script

*Follow this exact step-by-step walkthrough during your live demonstration.*

---

## 🛠️ Pre-Demo Setup Checklist (Do This 5 Minutes Before Entering)
1. **Ensure Python virtual environment is ready:**
   ```powershell
   cd c:\Users\jayant\Desktop\LPU-SmartNotice
   .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
2. **Open browser:** Navigate to `http://localhost:8000`.
3. **Open secondary tab:** Navigate to `http://localhost:8000/docs` (Swagger UI).
4. **Open third tab:** Navigate to `http://localhost:8000/api/v1/health`.

---

## ⏱️ The 5-Minute Demonstration Flow

### Minute 1: System Health & Subsystem Architecture
* **What to do:** Switch to the `http://localhost:8000/api/v1/health` tab.
* **What to say:**
  > *"Respected examiners, before demonstrating user interactions, here is our live subsystem health endpoint. As you can see, our FastAPI backend, SQLite database (with 94 live notices and 151 extracted metadata rows), and ChromaDB vector store (with 400 indexed documents) are all reporting healthy. Our total corpus consists of 7,444 official LPU announcements."*

---

### Minute 2: Multi-Student Profile Switching & Personalized Feed
* **What to do:** Switch to the main UI (`http://localhost:8000`).
* **Step 1:** Look at the left sidebar under **Active Student Context**.
* **Step 2:** Click the dropdown and select **"Aarav Sharma (B.Tech Computer Science - Year 3)"**.
* **Step 3:** Notice how the feed instantly updates with high-priority notices for 3rd-year CSE students (hackathons, software engineering internships, lab schedules).
* **Step 4:** Switch to another profile or click **"+ Add Student"** to show that students can enter their custom registration number, branch, semester, and timetable.
* **What to say:**
  > *"Notice how the feed is dynamically personalized. Rather than a chronological dump of 7,000 notices, each announcement receives a mathematical score from 0.0 to 1.0 based on the student's year, branch, and personal interests. Notices with group exclusions or mismatched target years are automatically filtered out."*

---

### Minute 3: Room & Timetable Impact Detection
* **What to do:** Click on **"Room & Timetable Impact"** in the left navigation sidebar.
* **What to see:** The table lists courses like `CSE316` scheduled in Room `34-304X`. Notice the red or yellow impact warning badge:
  * `Status: AFFECTED`
  * `Impact: Room 34-304X is exempted for External Agency Examination.`
* **What to say:**
  > *"Here is our proactive conflict detection. The system parses room numbers from announcements—normalizing formats like '34304X' into '34-304X'—and intersects the exemption hours with the student's enrolled class schedule. If an external exam or event displaces their class, the student is notified proactively before arriving at the venue."*

---

### Minute 4: The Grounded RAG Assistant in Action
* **What to do:** Click on **"AI Assistant (RAG)"** in the navigation menu.
* **Query 1:** Type:
  ```text
  When was the last date to fill in the accommodation details?
  ```
  and click **Send**.
* **Observe the answer:**
  * Identifies the exact deadline: **26 October 2026 (Monday)**.
  * Identifies the publication date: **22 October 2026**.
  * Explains the action: Open LPU Touch App -> Side Menu -> Accommodation Details.
  * Cites exact Source ID: `ANN-UMS-...` and reference `LPU/10.2/ANN/2024/023/IC/261022/0086`.
* **What to say:**
  > *"This query demonstrates our RAG engine solving the classic vocabulary mismatch problem. The student searched for 'accommodation', but the administrative title was 'Student PG/Residential Address Details'. Through Gemini vector embeddings in ChromaDB, the system grasped the semantic intent, extracted the explicit deadline rather than confusing it with the publication date, and provided verifiable source badges."*

---

### Minute 5: Attachment Awareness & Handling Incomplete Evidence
* **Query 2:** In the chat, type:
  ```text
  Who is shortlisted for the Google placement drive?
  ```
* **Observe the answer:**
  * Notice mentions an attachment (`Google_Shortlist.xlsx`), but explains that the binary spreadsheet is not stored in the system.
  * Warns the student to check the official UMS portal directly.
* **What to say:**
  > *"Notice that the model did not hallucinate a fake list of student names. Because our pipeline tracks 'DecisionCompleteness: ATTACHMENT_MISSING', the model honestly informs the user that an attachment was referenced by the administration but its binary contents are unavailable. This ensures institutional trust and zero fabrication."*

---

## 🛡️ Emergency Fallback Plan (If Live Network / API Drops)

| Scenario | What Happens | What to Say / Do |
|---|---|---|
| **Internet goes down / Gemini API 503:** | The backend automatically catches the error and falls back to **offline lexical search** and deterministic pseudo-embeddings. | *"Our architecture was designed with offline resilience. As you can see, when external cloud APIs are unavailable, our local SQLite and lexical retrieval services still return the verified announcements directly to the student."* |
| **ChromaDB count is lower than expected:** | Open Swagger UI at `http://localhost:8000/docs` -> expand `POST /api/v1/ums/import` -> click **Try it out**. | *"ChromaDB performs incremental on-demand indexing to optimize memory. Raw historical announcements remain 100% searchable in SQLite and JSON even before vector embeddings are generated."* |
| **Port 8000 already in use:** | Run `Get-Process python* | Stop-Process -Force` in PowerShell, then rerun uvicorn. | Takes 3 seconds to restart cleanly. |

