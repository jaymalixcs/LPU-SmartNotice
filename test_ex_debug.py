from app.services.room_impact_service import RoomImpactService
from app.services.dataset_service import DatasetService
from app.models.student import TimetableEntry

service = RoomImpactService()
dataset = DatasetService()
announcements, _ = dataset.load_dataset(include_live=True)

ann = None
for a in announcements:
    if a.announcement_id == "ANN-UMS-20261026-366be8359996":
        ann = a
        break

entry = TimetableEntry(
    entry_id="test", student_id="12404501", day_or_date="2026-10-28",
    start_time="09:00 AM", end_time="10:00 AM", course_code="CSE316",
    course_name="OS", room="34-304X", building="Block 34"
)

ann_text = f"{ann.title} {ann.full_content}".lower()
print("Ann text:\n", ann_text)

import re
except_patterns = [
    r"(?:except|excluding|exempted|exemption for)\s*(?:room|rooms)?\s*(\d{1,2}-\d{3}[A-Za-z]?)",
    r"(?:except|excluding|exempted)\s*(?:in|for)?\s*(?:block\s*\d{1,2}\s*)?(?:room\s*)?(\d{1,2}-\d{3}[A-Za-z]?)",
    r"(\d{1,2}-\d{3}[A-Za-z]?)\s*(?:and\s*(\d{1,2}-\d{3}[A-Za-z]?))?\s*(?:are|is)?\s*(?:explicitly\s*)?(?:exempted|exempt)"
]
for pat in except_patterns:
    print("Pattern:", pat)
    print("Matches:", re.findall(pat, ann_text))

