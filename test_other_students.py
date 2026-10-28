import requests

for stu_id in ['12215678', 'STU-101']:
    r = requests.get(f"http://127.0.0.1:8000/api/v1/feed/{stu_id}/affected-classes")
    data = r.json()
    print(f"\nStudent: {data.get('student_name')} ({stu_id})")
    for imp in data.get("impacts", []):
        print(f"  Room: {imp['entry']['room']} | Status: {imp['status']} | Affected: {imp['affected']} | Notice: {imp.get('announcement_title')}")

