from app.models.student import TimetableEntry
from app.services.room_impact_service import RoomImpactService
from app.services.dataset_service import DatasetService

service = RoomImpactService()
dataset = DatasetService()
announcements, _ = dataset.load_dataset(include_live=True)

entry = TimetableEntry(
    entry_id="test-1",
    student_id="12404501",
    day_or_date="2026-10-28",
    start_time="09:00 AM",
    end_time="10:00 AM",
    course_code="CSE301",
    course_name="Data Structures & Algorithms",
    room="34-303",
    building="Block 34"
)

print(f"Testing for room {entry.room} in {entry.building} on {entry.day_or_date}...")
matches = []
for ann in announcements[:100]:
    res = service.check_timetable_conflict(entry, ann)
    if res.affected:
        matches.append((ann.title, res.status, res.impact_type, res.explanation))

print(f"Total matching impacts: {len(matches)}")
for m in matches:
    print(m)

