import sqlite3
import json

conn = sqlite3.connect('storage/smartnotice.db')
c = conn.cursor()
c.execute("SELECT raw_metadata_json FROM extracted_metadata WHERE announcement_id = 'ANN-UMS-20261026-366be8359996'")
row = c.fetchone()
if row:
    print(json.loads(row[0]))

