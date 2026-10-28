from app.services.room_impact_service import RoomImpactService
from app.services.extraction_service import ExtractionService
from app.models.student import TimetableEntry
from app.models.announcement import RawAnnouncement
import sqlite3

conn = sqlite3.connect('storage/smartnotice.db')
c = conn.cursor()
c.execute("SELECT * FROM live_announcements WHERE announcement_id = 'ANN-UMS-20261026-366be8359996'")
row = c.fetchone()
ann = RawAnnouncement(
    announcement_id=row[0],
    title=row[1],
    publication_date=row[2],
    reference_number=row[3],
    full_content=row[4],
    attachment_present=bool(row[5]),
    content_hash=row[7]
)

ext = ExtractionService()
meta = ext.get_cached_metadata(ann.content_hash)
print("Cached metadata exempted_rooms:", meta.exempted_rooms if meta else None)

service = RoomImpactService()
entry = TimetableEntry(
    entry_id="test", student_id="12404501", day_or_date="2026-10-28",
    start_time="09:00 AM", end_time="10:00 AM", course_code="CSE316",
    course_name="OS", room="34-304X", building="Block 34"
)

res = service.check_timetable_conflict(entry, ann, meta)
print("Result status:", res.status)
print("Result evidence:", res.evidence_text)

