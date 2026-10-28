import sqlite3

conn = sqlite3.connect('storage/smartnotice.db')
c = conn.cursor()
c.execute("SELECT * FROM student_timetables")
for r in c.fetchall():
    print(r)

