import sqlite3
import json

conn = sqlite3.connect('storage/smartnotice.db')
c = conn.cursor()
c.execute("SELECT announcement_id, title, full_content FROM live_announcements WHERE title LIKE '%MindMatrix%' OR full_content LIKE '%MindMatrix%'")
rows = c.fetchall()
print("MindMatrix in live_announcements:", len(rows))
for r in rows:
    print(r[0], '|', r[1], '|', r[2][:200])

data = json.load(open('data/all_announcements_with_attachment_flag.json', encoding='utf-8'))
for d in data[:50]:
    if 'mindmatrix' in d.get('title', '').lower() or 'mindmatrix' in d.get('full_content', '').lower():
        print("Found in JSON:", d.get('title'), '| Content:', d.get('full_content')[:200])

