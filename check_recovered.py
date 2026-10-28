import json
import sqlite3

with open("recovered_announcements.json", "r", encoding="utf-8") as f:
    recovered = json.load(f)

print(f"Total recovered in JSON: {len(recovered)}")

conn = sqlite3.connect("storage/smartnotice.db")
c = conn.cursor()
c.execute("SELECT announcement_id, title, publication_date FROM live_announcements")
current_live = c.fetchall()
print(f"Currently in live_announcements table: {len(current_live)}")

curr_ids = {r[0] for r in current_live}
missing = [item for item in recovered if item["announcement_id"] not in curr_ids]
print(f"Missing from live_announcements: {len(missing)}")

# Sample of missing
for item in missing[:5]:
    print(f" - {item['announcement_id']}: {item['title'][:40]} ({item['publication_date']})")

