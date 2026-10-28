from app.services.room_impact_service import RoomImpactService
from app.services.dataset_service import DatasetService
from app.models.student import TimetableEntry

service = RoomImpactService()
dataset = DatasetService()
announcements, _ = dataset.load_dataset(include_live=True)

entry = TimetableEntry(
    entry_id="test", student_id="12404501", day_or_date="2026-10-28",
    start_time="09:00 AM", end_time="10:00 AM", course_code="CSE316",
    course_name="OS", room="34-304X", building="Block 34"
)

for ann in announcements[:100]:
    res = service.check_timetable_conflict(entry, ann)
    if res.status != "NO_MATCH":
        print(f"Announcement: {ann.announcement_id} | {ann.title[:40]} -> {res.status}")

