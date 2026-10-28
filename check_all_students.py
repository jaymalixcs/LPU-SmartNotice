import sqlite3
import json

conn = sqlite3.connect('storage/smartnotice.db')
c = conn.cursor()
c.execute("SELECT student_id, name FROM student_profiles")
for r in c.fetchall():
    c.execute("SELECT room, day_or_date, course_code FROM student_timetables WHERE student_id = ?", (r[0],))
    tt = c.fetchall()
    print(r[0], '|', r[1], '| Classes:', tt)

