import requests

# 1. Ingest the official suspension notice
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
print("Ingest status:", res.status_code)

# 2. Check Aarav Sharma's affected classes
r = requests.get("http://127.0.0.1:8000/api/v1/feed/STU-101/affected-classes")
data = r.json()
print("\n--- Aarav Sharma (STU-101) ---")
for imp in data.get("impacts", []):
    print(f"  Room: {imp['entry']['room']} | Status: {imp['status']} | Affected: {imp['affected']} | Notice: {imp.get('announcement_title')[:45] if imp.get('announcement_title') else 'None'}")

# 3. Check Jayant's affected classes
r2 = requests.get("http://127.0.0.1:8000/api/v1/feed/12404501/affected-classes")
data2 = r2.json()
print("\n--- Jayant (12404501) ---")
for imp in data2.get("impacts", []):
    print(f"  Room: {imp['entry']['room']} | Status: {imp['status']} | Affected: {imp['affected']} | Notice: {imp.get('announcement_title')[:45] if imp.get('announcement_title') else 'None'}")

