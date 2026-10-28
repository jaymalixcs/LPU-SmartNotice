import sqlite3

conn = sqlite3.connect('storage/smartnotice.db')
c = conn.cursor()
c.execute("SELECT announcement_id, title FROM live_announcements WHERE title LIKE '%SUSPENSION%'")
for r in c.fetchall():
    print(r)

