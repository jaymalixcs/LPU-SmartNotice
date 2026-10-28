import sqlite3

conn = sqlite3.connect('storage/smartnotice.db')
c = conn.cursor()
c.execute("SELECT full_content FROM live_announcements WHERE announcement_id = 'ANN-UMS-20261027-4f9547bf88e0'")
r = c.fetchone()
if r:
    print(r[0])

