from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from app.services.dataset_service import DatasetService
from app.services.personalization_service import PersonalizationService
from app.services.room_impact_service import RoomImpactService
from app.services.extraction_service import ExtractionService
from app.core.database import get_db_connection
from app.models.student import StudentProfile, ClassImpactResult

router = APIRouter(tags=["Personalization & Timetable Impact"])

dataset_service = DatasetService()
personalization_service = PersonalizationService()
room_impact_service = RoomImpactService()
extraction_service = ExtractionService()

def fetch_student_profile(student_id: str) -> StudentProfile:
    """Fetch student profile from SQLite DB."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM student_profiles WHERE student_id = ?", (student_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Student profile '{student_id}' not found.")

    import json
    interests = json.loads(row["interests"]) if row["interests"] else []
    return StudentProfile(
        student_id=row["student_id"],
        name=row["name"],
        program=row["program"],
        department=row["department"],
        school=row["school"],
        year=row["year"],
        semester=row["semester"],
        section=row["section"],
        interests=interests,
        career_goal=row["career_goal"]
    )

@router.get("/students/{student_id}/feed")
@router.get("/feed/{student_id}/feed")
def get_personalized_feed(
    student_id: str,
    category: Optional[str] = None,
    applicability: Optional[str] = None,
    min_score: float = Query(0.0, ge=0.0, le=1.0),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50)
):
    """Retrieve personalized, ranked announcement feed for a student."""
    student = fetch_student_profile(student_id)
    announcements, _ = dataset_service.load_dataset()

    # Build extracted metadata map for sample
    extracted_map = {}
    for ann in announcements[:200]: # Optimize for fast feed rendering
        cached = extraction_service.get_cached_metadata(ann.content_hash or "")
        if not cached:
            cached = extraction_service.fallback_heuristic_extraction(ann)
        extracted_map[ann.announcement_id] = cached

    feed_result = personalization_service.personalize_feed(
        student=student,
        announcements=announcements,
        extracted_map=extracted_map,
        category_filter=category,
        applicability_filter=applicability,
        min_score=min_score,
        page=page,
        page_size=page_size
    )
    return feed_result

@router.get("/students/{student_id}/affected-classes")
@router.get("/feed/{student_id}/affected-classes")
def get_affected_classes(student_id: str):
    """Evaluate student's timetable against announcements for room & time impact."""
    student = fetch_student_profile(student_id)
    timetable_entries = room_impact_service.get_sample_timetable(student_id)
    announcements, _ = dataset_service.load_dataset(include_live=True)

    impact_results = []
    for entry in timetable_entries:
        # Check against recent announcements
        entry_impacts = []
        for ann in announcements[:100]:
            cached_meta = extraction_service.get_cached_metadata(ann.content_hash or "")
            res = room_impact_service.check_timetable_conflict(entry, ann, cached_meta)
            if res.affected or res.status == "EXEMPTED":
                entry_impacts.append(res)

        if entry_impacts:
            # Pick the most specific and severe impact: CONFIRMED_MATCH > EXEMPTED > ATTACHMENT_DEPENDENT > POTENTIAL_IMPACT
            priority = {"CONFIRMED_MATCH": 1, "EXEMPTED": 2, "ATTACHMENT_DEPENDENT": 3, "POTENTIAL_IMPACT": 4}
            entry_impacts.sort(key=lambda x: priority.get(x.status, 5))
            impact_results.append(entry_impacts[0])
        else:
            impact_results.append(
                ClassImpactResult(
                    entry=entry,
                    affected=False,
                    status="NO_MATCH",
                    explanation=f"No room or schedule conflicts detected for {entry.course_code} ({entry.room})."
                )
            )

    return {
        "student_id": student.student_id,
        "student_name": student.name,
        "timetable_entries_checked": len(timetable_entries),
        "impacts": [imp.model_dump() for imp in impact_results]
    }
