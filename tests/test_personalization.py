from app.services.personalization_service import PersonalizationService

def test_personalization_scoring(sample_student_profile, sample_raw_announcement, sample_extracted_metadata):
    service = PersonalizationService()
    scores = service.score_announcement(sample_student_profile, sample_raw_announcement, sample_extracted_metadata)

    assert scores["personal_priority_score"] > 0.6
    assert scores["year_match_score"] == 1.0
    assert scores["dept_match_score"] == 1.0
    assert "Targeted for Year 3" in scores["explanation"]

def test_global_importance_override(sample_student_profile, sample_raw_announcement, sample_extracted_metadata):
    service = PersonalizationService()

    # Modify metadata to simulate urgent university-wide notice
    sample_extracted_metadata.target_year = [1] # Mismatched year (Year 1 vs Student Year 3)
    sample_extracted_metadata.global_importance = "HIGH"

    scores = service.score_announcement(sample_student_profile, sample_raw_announcement, sample_extracted_metadata)

    assert scores["is_override"] is True
    assert scores["personal_priority_score"] >= 0.85
    assert "override" in scores["explanation"].lower()
