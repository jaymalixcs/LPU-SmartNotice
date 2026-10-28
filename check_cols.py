import sqlite3

conn = sqlite3.connect('storage/smartnotice.db')
c = conn.cursor()
c.execute("PRAGMA table_info(extracted_metadata)")
for col in c.fetchall():
    print(col[1])
c.execute("SELECT * FROM extracted_metadata WHERE announcement_id = 'ANN-UMS-20261026-366be8359996'")
print("Row:", c.fetchone())

