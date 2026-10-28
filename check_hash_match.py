import sqlite3

conn = sqlite3.connect('storage/smartnotice.db')
c = conn.cursor()
c.execute("SELECT content_hash, affected_rooms, exempted_rooms FROM extracted_metadata WHERE announcement_id = 'ANN-UMS-20261026-366be8359996'")
row = c.fetchone()
print("Extracted metadata row:", row)
c.execute("SELECT announcement_id, content_hash FROM live_announcements WHERE announcement_id = 'ANN-UMS-20261026-366be8359996'")
print("Live announcement row:", c.fetchone())

