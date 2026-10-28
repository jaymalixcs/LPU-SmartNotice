import sqlite3
import json

conn = sqlite3.connect('storage/smartnotice.db')
c = conn.cursor()
c.execute("SELECT announcement_id, title, full_content FROM live_announcements WHERE full_content LIKE '%room%' OR full_content LIKE '%block%' OR full_content LIKE '%exempt%' OR full_content LIKE '%suspend%'")
rows = c.fetchall()
print(f"Live announcements with room/block keywords: {len(rows)}")
for r in rows:
    print(" -", r[0], "|", r[1])

data = json.load(open('data/all_announcements_with_attachment_flag.json', encoding='utf-8'))
json_rooms = [d for d in data if any(k in d.get('full_content', '').lower() for k in ['suspended', 'exempted', '34304x', '34-304x'])]
print(f"JSON announcements with room/block keywords: {len(json_rooms)}")
for d in json_rooms[:5]:
    print(" - JSON:", d.get('title'), "| Ref:", d.get('reference_number'))

