import sqlite3

conn = sqlite3.connect('storage/smartnotice.db')
c = conn.cursor()
c.execute("SELECT announcement_id, title, publication_date, reference_number FROM live_announcements")
rows = c.fetchall()
print(f"Total live announcements: {len(rows)}")
for r in rows:
    print(f"  {r[0]} | {r[1][:50]} | {r[2]} | {r[3][:25] if r[3] else ''}")

