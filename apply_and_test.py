import sqlite3
import requests

# 1. Update Jayant's timetable in SQLite to cover all 4 impact states
conn = sqlite3.connect('storage/smartnotice.db')
c = conn.cursor()
c.execute("DELETE FROM student_timetables WHERE student_id = '12404501'")
jayant_tt = [
    ('TT-12404501-1', '12404501', '2026-10-28', '09:00 AM', '10:00 AM', 'CSE316', 'Operating Systems', '34-304X', 'Block 34', 'Dr. Singh'),
    ('TT-12404501-2', '12404501', '2026-10-28', '10:00 AM', '11:00 AM', 'INT219', 'Front End Web Development', '34-101', 'Block 34', 'Prof. Gupta'),
    ('TT-12404501-3', '12404501', '2026-10-28', '11:00 AM', '12:00 PM', 'CSE301', 'Data Structures & Algorithms', '34-303', 'Block 34', 'Dr. Sharma'),
    ('TT-12404501-4', '12404501', '2026-10-28', '02:00 PM', '03:00 PM', 'MTH202', 'Discrete Mathematics', '32-201', 'Block 32', 'Prof. Verma')
]
c.executemany("""
    INSERT INTO student_timetables (entry_id, student_id, day_or_date, start_time, end_time, course_code, course_name, room, building, faculty)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", jayant_tt)
conn.commit()
conn.close()
print("Updated Jayant's timetable in SQLite.")

# 2. Ingest the official suspension notice
notices = [{
    "announcement_id": "ANN-UMS-20261026-0045",
    "title": "SUSPENSION OF CLASSES - Conduct of External Agency Examination in Block 34",
    "reference_number": "LPU/10.2/ANN(EXAM)/2024/023/IC/261026/0045",
    "publication_date": "2026-10-26",
    "attachment_present": True,
    "full_content": """SUSPENSION OF CLASSES FOR CONDUCT OF EXTERNAL AGENCY EXAMINATION

It is hereby notified to all faculty members and students that in view of the External Agency Examination scheduled on 27th & 28th October 2026, regular classes stand SUSPENDED in the following venues:

1. Building 34 (Block 34):
- Rooms 34304X, 34306, 34306X: Suspended for the entire day on 27th & 28th October 2026.
- Rooms 34-101 and 34-102: Explicitly EXEMPTED from suspension (classes in 34-101 and 34-102 will be conducted normally).

2. Building 32:
- Examination seating allocated across upper levels. Please refer attachment for complete list of secondary room relocations.

Division of Examination
Lovely Professional University"""
}]

res = requests.post("http://127.0.0.1:8000/api/v1/ums/import", json={"announcements": notices})
print("Notice Ingest status:", res.status_code)

# 3. Test API for Jayant
r = requests.get("http://127.0.0.1:8000/api/v1/feed/12404501/affected-classes")
data = r.json()
print("\n--- Jayant (12404501) Timetable Impact Results ---")
for imp in data.get("impacts", []):
    print(f"  Room: {imp['entry']['room']:8} | Course: {imp['entry']['course_code']:6} | Status: {imp['status']:20} | Affected: {str(imp['affected']):5} | {imp['explanation'][:70]}")

