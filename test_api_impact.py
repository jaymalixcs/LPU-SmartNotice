import requests

r = requests.get("http://127.0.0.1:8000/api/v1/feed/12404501/affected-classes")
print("Status:", r.status_code)
data = r.json()
print("Student:", data.get("student_name"))
print("Total entries:", len(data.get("impacts", [])))
for imp in data.get("impacts", []):
    print(f"  {imp['entry']['room']} | Status: {imp['status']} | Affected: {imp['affected']} | {imp['explanation']}")

