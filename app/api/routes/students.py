import json
import uuid
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, status
from app.core.database import get_db_connection
from app.models.student import StudentProfile, CreateStudentRequest, TimetableEntry

router = APIRouter(prefix="/students", tags=["Student Profiles"])

@router.get("", response_model=List[StudentProfile])
def list_demo_students():
    """List all registered and demo student profiles."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM student_profiles 
        ORDER BY CASE WHEN student_id LIKE 'STU-%' THEN 0 ELSE 1 END, student_id
    """)
    rows = cursor.fetchall()
    conn.close()

    students = []
    for r in rows:
        interests = json.loads(r["interests"]) if r["interests"] else []
        students.append(
            StudentProfile(
                student_id=r["student_id"],
                name=r["name"],
                program=r["program"],
                department=r["department"],
                school=r["school"] or "",
                year=r["year"],
                semester=r["semester"],
                section=r["section"] or "",
                interests=interests,
                career_goal=r["career_goal"] or ""
            )
        )
    return students

@router.post("", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
def create_student(req: CreateStudentRequest):
    """Register a new student profile along with their full timetable."""
    stu_id = req.student_id.strip()
    name = req.name.strip()
    program = req.program.strip()
    department = req.department.strip()

    if not stu_id or not name or not program:
        raise HTTPException(
            status_code=400,
            detail="Registration Number/ID, Student Name, and Program/Stream are required."
        )

    school = req.school.strip() if req.school else f"School of {department.replace('Department of ', '')}"

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 1. Insert or replace profile
        interests_json = json.dumps(req.interests)
        cursor.execute("""
        INSERT INTO student_profiles (
            student_id, name, program, department, school, year, semester, section, interests, career_goal
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(student_id) DO UPDATE SET
            name=excluded.name,
            program=excluded.program,
            department=excluded.department,
            school=excluded.school,
            year=excluded.year,
            semester=excluded.semester,
            section=excluded.section,
            interests=excluded.interests,
            career_goal=excluded.career_goal
        """, (
            stu_id,
            name,
            program,
            department,
            school,
            req.year,
            req.semester,
            req.section or "",
            interests_json,
            req.career_goal or ""
        ))

        # 2. Insert timetable entries
        # Remove existing timetable entries for this student if re-registering
        cursor.execute("DELETE FROM student_timetables WHERE student_id = ?", (stu_id,))

        tt_count = 0
        for idx, entry in enumerate(req.timetable):
            entry_id = f"TT-{stu_id}-{idx + 1}"
            raw_room = entry.room.strip()
            building = entry.building.strip() if entry.building else ""
            if not building and "-" in raw_room:
                building = f"Block {raw_room.split('-')[0]}"
            elif not building and len(raw_room) >= 4 and raw_room[:2].isdigit():
                building = f"Block {raw_room[:2]}"

            cursor.execute("""
            INSERT INTO student_timetables (
                entry_id, student_id, day_or_date, start_time, end_time,
                course_code, course_name, room, building, faculty
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry_id,
                stu_id,
                entry.day_or_date.strip(),
                entry.start_time.strip(),
                entry.end_time.strip(),
                entry.course_code.strip(),
                entry.course_name.strip(),
                raw_room,
                building or "Campus",
                entry.faculty.strip() if entry.faculty else ""
            ))
            tt_count += 1

        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to save student profile: {str(exc)}")
    finally:
        conn.close()

    return {
        "status": "success",
        "message": f"Student '{name}' ({stu_id}) registered successfully with {tt_count} timetable classes.",
        "student_id": stu_id,
        "classes_count": tt_count
    }

@router.get("/{student_id}")
def get_student_details(student_id: str):
    """Get student profile and their registered timetable."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM student_profiles WHERE student_id = ?", (student_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Student '{student_id}' not found.")

    interests = json.loads(row["interests"]) if row["interests"] else []
    profile = StudentProfile(
        student_id=row["student_id"],
        name=row["name"],
        program=row["program"],
        department=row["department"],
        school=row["school"] or "",
        year=row["year"],
        semester=row["semester"],
        section=row["section"] or "",
        interests=interests,
        career_goal=row["career_goal"] or ""
    )

    cursor.execute("SELECT * FROM student_timetables WHERE student_id = ? ORDER BY day_or_date, start_time", (student_id,))
    tt_rows = cursor.fetchall()
    conn.close()

    timetable = [
        TimetableEntry(
            entry_id=tr["entry_id"],
            student_id=tr["student_id"],
            day_or_date=tr["day_or_date"],
            start_time=tr["start_time"],
            end_time=tr["end_time"],
            course_code=tr["course_code"],
            course_name=tr["course_name"],
            room=tr["room"],
            building=tr["building"] or "",
            faculty=tr["faculty"] or ""
        ) for tr in tt_rows
    ]

    return {
        "profile": profile,
        "timetable": timetable
    }

@router.delete("/{student_id}")
def delete_student(student_id: str):
    """Delete a custom student profile and their timetable."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM student_timetables WHERE student_id = ?", (student_id,))
    cursor.execute("DELETE FROM student_profiles WHERE student_id = ?", (student_id,))
    conn.commit()
    conn.close()
    return {"status": "success", "message": f"Student '{student_id}' deleted."}
