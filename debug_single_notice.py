from app.services.room_impact_service import RoomImpactService
from app.services.dataset_service import DatasetService
from app.models.student import TimetableEntry

service = RoomImpactService()
dataset = DatasetService()
announcements, _ = dataset.load_dataset(include_live=True)

target_ann = None
for a in announcements:
    if a.announcement_id == "ANN-UMS-20261026-0045":
        target_ann = a
        break

print("Target announcement found:", target_ann is not None)
if target_ann:
    print("Title:", target_ann.title)
    print("Attachment present:", target_ann.attachment_present)

for room in ["34-304X", "34-101", "32-201", "34-303"]:
    entry = TimetableEntry(
        entry_id="test", student_id="12404501", day_or_date="2026-10-28",
        start_time="09:00 AM", end_time="10:00 AM", course_code="CSE101",
        course_name="Test", room=room, building="Block 34" if "34" in room else "Block 32"
    )
    res = service.check_timetable_conflict(entry, target_ann)
    print(f"Room: {room:8} -> Status: {res.status:20} Affected: {res.affected}")

