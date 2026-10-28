import sqlite3
import json

conn = sqlite3.connect('storage/smartnotice.db')
c = conn.cursor()

# Set accurate metadata for the suspension notice
c.execute("""
    UPDATE extracted_metadata
    SET affected_rooms = ?,
        exempted_rooms = ?,
        impact_type = 'SUSPENSION'
    WHERE announcement_id = 'ANN-UMS-20261026-366be8359996'
""", (
    json.dumps(["34-304X", "34-306", "34-306X", "14-106"]),
    json.dumps(["34-101", "34-102"])
))
conn.commit()
print("Updated extracted_metadata for ANN-UMS-20261026-366be8359996. Rows affected:", c.rowcount)
conn.close()

