import json
import sqlite3
from app.services.dataset_service import DatasetService
from app.services.vector_store_service import VectorStoreService

with open("recovered_announcements.json", "r", encoding="utf-8") as f:
    recovered = json.load(f)

conn = sqlite3.connect("storage/smartnotice.db")
c = conn.cursor()

c.execute("SELECT announcement_id FROM live_announcements")
existing_ids = {r[0] for r in c.fetchall()}

restored = 0
for item in recovered:
    aid = item.get("announcement_id")
    if aid not in existing_ids:
        c.execute("""
            INSERT INTO live_announcements (
                announcement_id, source_id, title, publication_date,
                reference_number, full_content, attachment_present,
                attachment_names, content_hash, source, source_url,
                revision_count, created_at, updated_at, processing_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'INDEXED')
        """, (
            aid,
            aid,
            item.get("title", ""),
            item.get("publication_date", "2026-10-28"),
            item.get("reference_number", ""),
            item.get("full_content", ""),
            1 if item.get("attachment_present") else 0,
            json.dumps(item.get("attachment_names", [])),
            item.get("content_hash", ""),
            item.get("source", "ums"),
            item.get("source_url", "https://ums.lpu.in/lpuums/StudentDashboard.aspx")
        ))
        restored += 1

conn.commit()
print(f"Restored {restored} announcements to SQLite live_announcements table.")

# Check total count in live_announcements
c.execute("SELECT count(*) FROM live_announcements")
total = c.fetchone()[0]
print(f"Total live announcements now: {total}")
conn.close()

# Also ensure Vector Store indexing
try:
    vstore = VectorStoreService()
    docs = []
    metas = []
    ids = []
    for item in recovered:
        aid = item.get("announcement_id")
        docs.append(f"{item.get('title', '')}\n{item.get('full_content', '')}")
        metas.append({
            "announcement_id": aid,
            "title": item.get("title", "")[:100],
            "publication_date": item.get("publication_date", "2026-10-28"),
            "category": "UMS Live Announcement",
            "source": "ums"
        })
        ids.append(aid)
    
    # Upsert in batches of 20
    for i in range(0, len(ids), 20):
        vstore.collection.upsert(
            documents=docs[i:i+20],
            metadatas=metas[i:i+20],
            ids=ids[i:i+20]
        )
    print(f"Successfully upserted {len(ids)} into ChromaDB collection.")
except Exception as e:
    print(f"ChromaDB indexing note: {e}")

# Clear dataset cache
DatasetService.clear_cache()
print("Dataset cache cleared.")

