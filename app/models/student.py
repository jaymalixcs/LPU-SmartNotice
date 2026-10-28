from typing import List, Optional
from pydantic import BaseModel, Field

class StudentProfile(BaseModel):
    """Represents a student profile for personalization and feed ranking."""
    student_id: str
    name: str
    program: str
    department: str
    school: str
    year: int
    semester: int
    section: Optional[str] = None
    interests: List[str] = Field(default_factory=list)
    career_goal: Optional[str] = None

class TimetableEntry(BaseModel):
    """Represents a scheduled class entry for a student."""
    entry_id: str
    student_id: str
    day_or_date: str # e.g. "Monday" or "2026-10-10"
    start_time: str # e.g. "09:00 AM"
    end_time: str # e.g. "10:00 AM"
    course_code: str # e.g. "CSE301"
    course_name: str # e.g. "Data Structures & Algorithms"
    room: str # e.g. "34-105"
    building: Optional[str] = "Block 34"
    faculty: Optional[str] = None

class TimetableEntryInput(BaseModel):
    """Input payload for a single class in student timetable."""
    day_or_date: str # e.g. "Monday" or "2026-10-27"
    start_time: str # e.g. "09:00 AM"
    end_time: str # e.g. "10:00 AM"
    course_code: str # e.g. "CSE301"
    course_name: str # e.g. "Data Structures & Algorithms"
    room: str # e.g. "34-105" or "34105"
    building: Optional[str] = None
    faculty: Optional[str] = None

class CreateStudentRequest(BaseModel):
    """Input payload to register a new student profile and their timetable."""
    student_id: str # Registration Number / ID e.g. "12204567"
    name: str # Student Name
    program: str # Stream / Degree e.g. "B.Tech Computer Science & Engineering"
    department: str # e.g. "Department of Computer Science"
    school: Optional[str] = ""
    year: int = 1
    semester: int = 1
    section: Optional[str] = ""
    interests: List[str] = Field(default_factory=list)
    career_goal: Optional[str] = ""
    timetable: List[TimetableEntryInput] = Field(default_factory=list)

class ClassImpactResult(BaseModel):
    """Represents the room impact analysis result for a student class."""
    entry: TimetableEntry
    affected: bool
    status: str # "CONFIRMED_MATCH", "EXEMPTED", "POTENTIAL_IMPACT", "ATTACHMENT_DEPENDENT", "NO_MATCH", "UNCERTAIN_DATA"
    impact_type: Optional[str] = "NONE" # "SUSPENSION", "VENUE_CHANGE", "EXAM_DUTY", "RESCHEDULED", "GENERAL_ALERT", "NONE"
    announcement_id: Optional[str] = None
    announcement_title: Optional[str] = None
    evidence_text: Optional[str] = None
    explanation: str
