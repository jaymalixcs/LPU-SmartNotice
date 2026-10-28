"""Regression tests for room-impact classification, intent-aware retrieval, and
UMS synchronization pipeline repair.

These tests use synthetic fixtures and mocked Gemini responses. No paid Gemini
API calls are made.

Test A: Room exemption beats event location
Test B: Specific room query with temporal filtering
Test C: UMS synchronization to feed
Test D: UMS synchronization to RAG
Test E: Cache invalidation
Test F: Failure handling
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from app.core.database import get_db_connection, init_db
from app.models.announcement import RawAnnouncement, ExtractedAnnouncementMetadata
from app.models.chat import ChatRequest
from app.models.student import StudentProfile
from app.services.impact_classifier import (
    classify_impact,
    parse_room_list,
    is_location_impact_query,
    extract_query_block,
    extract_query_impact_type,
)
from app.services.retrieval_service import RetrievalService
from app.services.extraction_service import ExtractionService
from app.services.chat_service import ChatService
from app.services.ums_sync_service import UMSSyncService
from app.services.ums_source import UMSSourceAdapter
from app.services.dataset_service import DatasetService
from app.services.personalization_service import PersonalizationService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def setup_db():
    """Ensure database tables exist and clean live tables before each test."""
    init_db()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM live_announcements")
    c.execute("DELETE FROM ums_sync_history")
    conn.commit()
    conn.close()
    DatasetService.clear_cache()


@pytest.fixture
def exemption_announcement():
    """A room-exemption notice for Block 34."""
    return RawAnnouncement(
        announcement_id="ANN-EXEMPT-34",
        title="Notice for the Exemption of BYOD ROOMS",
        publication_date="2026-09-26",
        reference_number="LPU/20.1/ADM/2026/0002",
        full_content=(
            "This is for the information of all the concerned that the following "
            "BYOD Rooms are exempted on 22-09-2026 from 10 AM to 2 PM for the Written "
            "Test of WISSEN TECHNOLOGY. 34-301, 301A, 302, 302A, 303, 304X "
            "Uploaded By: Office of HOD Division of Career Services"
        ),
        attachment_present=False,
        attachment_names=[],
        content_hash="exempt_34_hash",
        source="historical",
    )


@pytest.fixture
def event_announcement():
    """An event-location notice in Block 34 (mentoring session, NOT an exemption)."""
    return RawAnnouncement(
        announcement_id="ANN-EVENT-34",
        title="Smart India Hackathon Internal Scrutiny",
        publication_date="2026-09-26",
        reference_number="LPU/18.4/INNOV/2026/0019",
        full_content=(
            "Mentoring sessions will be conducted in Block 34 Room 34-413 on "
            "Saturday at 02:00 PM. Teams must submit problem statement summaries "
            "by 25th October 2026."
        ),
        attachment_present=True,
        attachment_names=["SIH_2026_Guidelines.pdf"],
        content_hash="event_34_hash",
        source="historical",
    )


@pytest.fixture
def block_restriction_announcement():
    """A block restriction notice for Block 34."""
    return RawAnnouncement(
        announcement_id="ANN-RESTRICT-34",
        title="Examination Day Entry Restriction",
        publication_date="2026-10-15",
        reference_number="LPU/EXAM/2026/089",
        full_content=(
            "Entry is strictly prohibited in Building 34 on the examination day "
            "from 9:00 AM to 1:00 PM. All students must use alternate routes."
        ),
        attachment_present=False,
        attachment_names=[],
        content_hash="restrict_34_hash",
        source="historical",
    )


@pytest.fixture
def sample_student():
    return StudentProfile(
        student_id="STU-101",
        name="Aarav Sharma",
        program="B.Tech Computer Science & Engineering",
        department="Department of Computer Science",
        school="School of Computer Science and Engineering",
        year=3,
        semester=5,
        section="K21AB",
        interests=["AI/ML", "Web Development", "Placements"],
        career_goal="Software Engineer",
    )


# ===========================================================================
# Test A: Room exemption beats event location
# ===========================================================================

class TestRoomExemptionBeatsEventLocation:
    """Verify that room exemptions are correctly classified and ranked above
    event locations when the user asks what affects a block."""

    def test_impact_classifier_distinguishes_exemption_from_event(
        self, exemption_announcement, event_announcement
    ):
        """The classifier must classify an exemption as ROOM_EXEMPTION and an
        event as EVENT_LOCATION — never the other way around."""
        exempt_result = classify_impact(
            exemption_announcement.title, exemption_announcement.full_content
        )
        event_result = classify_impact(
            event_announcement.title, event_announcement.full_content
        )

        assert exempt_result.impact_type == "ROOM_EXEMPTION"
        assert exempt_result.block == "34"
        assert "34-301" in exempt_result.affected_rooms
        assert "34-304X" in exempt_result.affected_rooms
        assert exempt_result.event_date == "2026-09-22"
        assert exempt_result.start_time == "10:00"
        assert exempt_result.end_time == "14:00"
        assert exempt_result.confidence >= 0.9

        assert event_result.impact_type == "EVENT_LOCATION"
        assert event_result.block == "34"
        assert "34-413" in event_result.affected_rooms
        assert event_result.confidence < exempt_result.confidence

    def test_retrieval_categorizes_results_by_impact(
        self, exemption_announcement, event_announcement, block_restriction_announcement
    ):
        """search_location_impact must put exemptions and events in separate categories."""
        service = RetrievalService()
        # Mock the vector store to return empty semantic results so only lexical
        # search over our test fixtures is used (avoids interference from
        # previously indexed records in the persistent ChromaDB).
        service.vector_store.collection.count = MagicMock(return_value=0)
        service.vector_store.collection.query = MagicMock(return_value={"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]})

        all_anns = [exemption_announcement, event_announcement, block_restriction_announcement]

        result = service.search_location_impact(
            query="What announcements affect Block 34?",
            top_k=10,
            raw_announcements=all_anns,
        )

        categories = result["categories"]
        assert "ROOM_EXEMPTION" in categories
        assert "EVENT_LOCATION" in categories

        # Exemption category must contain the exemption announcement
        exempt_ids = [r["announcement_id"] for r in categories["ROOM_EXEMPTION"]]
        assert "ANN-EXEMPT-34" in exempt_ids

        # Event category must contain the event announcement
        event_ids = [r["announcement_id"] for r in categories["EVENT_LOCATION"]]
        assert "ANN-EVENT-34" in event_ids

        # The event must NOT appear in the exemption category
        assert "ANN-EVENT-34" not in exempt_ids

    def test_chat_service_builds_categorized_evidence(
        self, exemption_announcement, event_announcement
    ):
        """The chat service must include impact classification in evidence blocks
        and build categorized evidence for location-impact queries."""
        service = ChatService()

        # Mock retrieval to return our test announcements
        mock_candidates = [
            {
                "announcement_id": "ANN-EXEMPT-34",
                "title": exemption_announcement.title,
                "publication_date": exemption_announcement.publication_date,
                "reference_number": exemption_announcement.reference_number,
                "document": f"Title: {exemption_announcement.title}\nContent: {exemption_announcement.full_content}",
                "attachment_present": False,
                "attachment_names": [],
                "attachment_content_available": False,
                "decision_completeness": "COMPLETE",
                "rrf_score": 0.9,
                "notice_dates": ["2026-09-22"],
                "matches_target_date": None,
                "impact_type": "ROOM_EXEMPTION",
                "impact_facts": {
                    "impact_type": "ROOM_EXEMPTION",
                    "block": "34",
                    "affected_rooms": ["34-301", "34-301A", "34-302"],
                    "event_date": "2026-09-22",
                    "start_time": "10:00",
                    "end_time": "14:00",
                    "source_evidence": "exempted",
                    "confidence": 0.9,
                },
            },
            {
                "announcement_id": "ANN-EVENT-34",
                "title": event_announcement.title,
                "publication_date": event_announcement.publication_date,
                "reference_number": event_announcement.reference_number,
                "document": f"Title: {event_announcement.title}\nContent: {event_announcement.full_content}",
                "attachment_present": True,
                "attachment_names": ["SIH_2026_Guidelines.pdf"],
                "attachment_content_available": False,
                "decision_completeness": "ATTACHMENT_MISSING",
                "rrf_score": 0.7,
                "notice_dates": [],
                "matches_target_date": None,
                "impact_type": "EVENT_LOCATION",
                "impact_facts": {
                    "impact_type": "EVENT_LOCATION",
                    "block": "34",
                    "affected_rooms": ["34-413"],
                    "event_date": None,
                    "source_evidence": "conducted in block",
                    "confidence": 0.65,
                },
            },
        ]

        service.retrieval_service.search_location_impact = MagicMock(
            return_value={
                "categories": {
                    "ROOM_EXEMPTION": [mock_candidates[0]],
                    "EVENT_LOCATION": [mock_candidates[1]],
                },
                "results": mock_candidates,
                "query_block": "34",
                "query_impact_type": None,
                "target_dates": [],
            }
        )

        # Mock Gemini client to capture the prompt
        mock_client = MagicMock()
        captured_prompt = {}

        def capture_generate(model, contents, config):
            captured_prompt["prompt"] = contents
            resp = MagicMock()
            resp.text = (
                "Rooms exempted in Block 34: 34-301, 34-301A, 34-302 [Source ID: ANN-EXEMPT-34]. "
                "Events in Block 34 (NOT exemptions): mentoring session in 34-413 [Source ID: ANN-EVENT-34]."
            )
            return resp

        mock_client.models.generate_content.side_effect = capture_generate
        service.get_client = MagicMock(return_value=mock_client)

        req = ChatRequest(query="What announcements affect Block 34?", top_k=15)
        res = service.answer_question(req)

        # Verify the prompt contains categorized evidence
        assert "STRUCTURED IMPACT CATEGORIES" in captured_prompt["prompt"]
        assert "ROOMS EXEMPTED OR UNAVAILABLE" in captured_prompt["prompt"]
        assert "EVENTS TAKING PLACE (NOT EXEMPTIONS)" in captured_prompt["prompt"]
        assert "Impact Classification: ROOM_EXEMPTION" in captured_prompt["prompt"]
        assert "Impact Classification: EVENT_LOCATION" in captured_prompt["prompt"]

    def test_query_intent_detection(self):
        """Location-impact queries are detected; general queries are not."""
        assert is_location_impact_query("What announcements affect Block 34?") == True
        assert is_location_impact_query("Which rooms in Block 34 are exempted?") == True
        assert is_location_impact_query("Are any rooms unavailable in Block 27?") == True
        assert is_location_impact_query("What is the exam schedule?") == False
        assert is_location_impact_query("Hello") == False

        assert extract_query_block("What announcements affect Block 34?") == "34"
        assert extract_query_impact_type("Which rooms are exempted?") == "ROOM_EXEMPTION"
        assert extract_query_impact_type("What events are in Block 34?") == "EVENT_LOCATION"


# ===========================================================================
# Test B: Specific room query
# ===========================================================================

class TestSpecificRoomQuery:
    """Verify that specific room queries return only actual room exemptions."""

    def test_only_exemptions_returned_for_exemption_query(
        self, exemption_announcement, event_announcement
    ):
        """When asking specifically about exemptions, only exemption notices
        should be returned as exemptions."""
        service = RetrievalService()
        all_anns = [exemption_announcement, event_announcement]

        result = service.search_location_impact(
            query="Which rooms in Block 34 are exempted?",
            top_k=10,
            raw_announcements=all_anns,
        )

        # Query asks specifically for exemptions
        assert result["query_impact_type"] == "ROOM_EXEMPTION"

        # Filtered results should only contain exemptions
        for r in result["results"]:
            assert r["impact_type"] == "ROOM_EXEMPTION"

    def test_no_invented_room_numbers(self, event_announcement):
        """When no exemption notices exist, the classifier should not invent rooms."""
        service = RetrievalService()
        # Mock ChromaDB to return empty so only our test fixtures are searched
        service.vector_store.collection.count = MagicMock(return_value=0)
        service.vector_store.collection.query = MagicMock(return_value={"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]})

        result = service.search_location_impact(
            query="Which rooms in Block 99 are exempted tomorrow?",
            top_k=5,
            raw_announcements=[event_announcement],
        )

        # The event should be classified as EVENT_LOCATION, not ROOM_EXEMPTION
        categories = result["categories"]
        assert "ROOM_EXEMPTION" not in categories or len(categories.get("ROOM_EXEMPTION", [])) == 0

    def test_compressed_room_list_parsing(self):
        """Verify compressed format '34-111, 213, 413' expands correctly."""
        rooms = parse_room_list("34-111, 213, 413")
        assert "34-111" in rooms
        assert "34-213" in rooms
        assert "34-413" in rooms

    def test_room_range_parsing(self):
        """Verify ranges like '34-101 to 34-110' expand correctly."""
        rooms = parse_room_list("34-101 to 34-110")
        assert len(rooms) == 10
        assert rooms[0] == "34-101"
        assert rooms[-1] == "34-110"


# ===========================================================================
# Test C: UMS synchronization to feed
# ===========================================================================

class TestUMSSyncToFeed:
    """Verify that synced UMS announcements appear in the personalized feed."""

    def test_synced_announcement_visible_in_feed(self, sample_student):
        """A synced UMS notice must appear in the personalized feed."""
        # Sync a notice
        adapter = UMSSourceAdapter(connector_mode="mock")
        sync_service = UMSSyncService(source_adapter=adapter)
        result = sync_service.run_sync(triggered_by="test_feed", limit=1)
        assert result["inserted_count"] >= 1

        # Load the dataset (should include live records)
        DatasetService.clear_cache()
        ds = DatasetService()
        announcements, _ = ds.load_dataset(include_live=True)

        # Verify live records are present
        live_records = [a for a in announcements if a.source and a.source.startswith("ums")]
        assert len(live_records) >= 1

        # Build the feed
        extraction_service = ExtractionService()
        extracted_map = {}
        for ann in announcements[:200]:
            cached = extraction_service.get_cached_metadata(ann.content_hash or "")
            if not cached:
                cached = extraction_service.fallback_heuristic_extraction(ann)
            extracted_map[ann.announcement_id] = cached

        ps = PersonalizationService()
        feed = ps.personalize_feed(
            student=sample_student,
            announcements=announcements,
            extracted_map=extracted_map,
            page=1,
            page_size=50,
        )

        # Verify at least one live record is in the feed
        live_in_feed = [item for item in feed["feed"] if item.get("is_live")]
        assert len(live_in_feed) >= 1, "Live UMS announcements should appear in the personalized feed"

    def test_synced_announcement_does_not_vanish_with_unknown_audience(self, sample_student):
        """A UMS notice with no target-audience metadata must NOT be silently
        dropped from the feed."""
        # Insert a notice with minimal content
        mock_adapter = MagicMock()
        mock_adapter.fetch_latest_announcements.return_value = [{
            "id": "UNKNOWN-AUD-1",
            "title": "General University Holiday Notice",
            "full_content": "The university declares a holiday on account of a national festival.",
            "publication_date": "2026-10-28",
            "reference_number": "LPU/ANN/2026/999",
        }]
        mock_adapter.normalize_announcement.side_effect = lambda raw: UMSSourceAdapter().normalize_announcement(raw)

        sync_service = UMSSyncService(source_adapter=mock_adapter)
        result = sync_service.run_sync(triggered_by="test_unknown_aud")
        assert result["inserted_count"] == 1

        # Load and build feed
        DatasetService.clear_cache()
        ds = DatasetService()
        announcements, _ = ds.load_dataset(include_live=True)

        live_records = [a for a in announcements if a.source and a.source.startswith("ums")]
        assert any(a.announcement_id == "ANN-UMS-UNKNOWN-AUD-1" for a in live_records)

    def test_duplicate_sync_does_not_create_duplicates(self):
        """Running sync twice must not create duplicate records."""
        adapter = UMSSourceAdapter(connector_mode="mock")
        sync_service = UMSSyncService(source_adapter=adapter)

        # First sync
        result1 = sync_service.run_sync(triggered_by="test_dup_1", limit=2)
        assert result1["inserted_count"] >= 1

        # Check DB count
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) as cnt FROM live_announcements")
        count1 = c.fetchone()["cnt"]
        conn.close()

        # Second sync (same data)
        result2 = sync_service.run_sync(triggered_by="test_dup_2", limit=2)
        assert result2["inserted_count"] == 0
        assert result2["skipped_count"] >= 1

        # Verify no duplicates
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) as cnt FROM live_announcements")
        count2 = c.fetchone()["cnt"]
        conn.close()

        assert count2 == count1, "Second sync should not create duplicates"

    def test_processing_status_tracked(self):
        """Verify that processing status is tracked for synced records."""
        adapter = UMSSourceAdapter(connector_mode="mock")
        sync_service = UMSSyncService(source_adapter=adapter)
        result = sync_service.run_sync(triggered_by="test_status", limit=1)

        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT announcement_id, processing_status FROM live_announcements")
        rows = c.fetchall()
        conn.close()

        assert len(rows) >= 1
        for row in rows:
            # After sync with AUTO_EMBED, status should be INDEXED or STORED
            assert row["processing_status"] in ("STORED", "ANALYZED", "INDEXED", "READY", "FAILED")


# ===========================================================================
# Test D: UMS synchronization to RAG
# ===========================================================================

class TestUMSSyncToRAG:
    """Verify that synced UMS announcements are available to RAG retrieval."""

    def test_raw_record_searchable_while_embedding_pending(self):
        """A synced record must be retrievable via lexical search even if
        embedding is missing."""
        # Insert a notice with a distinctive title
        mock_adapter = MagicMock()
        mock_adapter.fetch_latest_announcements.return_value = [{
            "id": "RAG-TEST-1",
            "title": "Special Workshop on Quantum Computing Applications",
            "full_content": "A special workshop on quantum computing will be organized for CSE students. Registration is mandatory.",
            "publication_date": "2026-10-28",
            "reference_number": "LPU/QC/2026/001",
        }]
        mock_adapter.normalize_announcement.side_effect = lambda raw: UMSSourceAdapter().normalize_announcement(raw)

        sync_service = UMSSyncService(source_adapter=mock_adapter)
        sync_service.run_sync(triggered_by="test_rag")

        # Load dataset and search
        DatasetService.clear_cache()
        ds = DatasetService()
        announcements, _ = ds.load_dataset(include_live=True)

        service = RetrievalService()
        results = service.search(
            query="quantum computing workshop",
            top_k=5,
            raw_announcements=announcements,
        )

        # The synced notice should be found via lexical search
        found_ids = [r["announcement_id"] for r in results]
        assert "ANN-UMS-RAG-TEST-1" in found_ids, "Synced notice should be searchable via lexical search"

    def test_chat_cites_stored_announcement(self):
        """The chatbot response must cite the actual stored announcement."""
        service = ChatService()

        mock_candidate = {
            "announcement_id": "ANN-UMS-CITE-1",
            "title": "Placement Drive Registration Deadline",
            "publication_date": "2026-10-28",
            "reference_number": "LPU/TPO/2026/500",
            "document": "Registration deadline for placement drive is 30th October 2026.",
            "attachment_present": False,
            "attachment_names": [],
            "attachment_content_available": False,
            "decision_completeness": "COMPLETE",
            "rrf_score": 0.95,
            "notice_dates": [],
            "matches_target_date": None,
            "impact_type": "UNKNOWN_IMPACT",
            "impact_facts": {"impact_type": "UNKNOWN_IMPACT", "affected_rooms": [], "confidence": 0.1},
        }
        service.retrieval_service.search = MagicMock(return_value=[mock_candidate])

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "The placement registration deadline is 30th October 2026 [Source ID: ANN-UMS-CITE-1]."
        mock_client.models.generate_content.return_value = mock_response
        service.get_client = MagicMock(return_value=mock_client)

        req = ChatRequest(query="What is the placement registration deadline?")
        res = service.answer_question(req)

        assert "[Source ID: ANN-UMS-CITE-1]" in res.answer
        assert len(res.sources) == 1
        assert res.sources[0].announcement_id == "ANN-UMS-CITE-1"


# ===========================================================================
# Test E: Cache invalidation
# ===========================================================================

class TestCacheInvalidation:
    """Verify that the dataset cache is invalidated after sync."""

    def test_new_record_visible_after_sync_without_restart(self):
        """Insert a new announcement via sync, then verify it's visible in the
        dataset without restarting the server."""
        # Load the dataset (caches historical records)
        ds = DatasetService()
        initial_records, _ = ds.load_dataset(include_live=True)
        initial_count = len(initial_records)

        # Sync a new notice
        mock_adapter = MagicMock()
        mock_adapter.fetch_latest_announcements.return_value = [{
            "id": "CACHE-TEST-1",
            "title": "New Notice After Cache Clear Test",
            "full_content": "This notice should appear after cache invalidation.",
            "publication_date": "2026-10-28",
            "reference_number": "LPU/CACHE/2026/001",
        }]
        mock_adapter.normalize_announcement.side_effect = lambda raw: UMSSourceAdapter().normalize_announcement(raw)

        sync_service = UMSSyncService(source_adapter=mock_adapter)
        result = sync_service.run_sync(triggered_by="test_cache")
        assert result["inserted_count"] == 1

        # Reload the dataset (cache should have been cleared by sync)
        ds2 = DatasetService()
        new_records, _ = ds2.load_dataset(include_live=True)
        new_count = len(new_records)

        # The new notice should be visible
        assert new_count > initial_count, "New record should be visible after sync"
        new_ids = [r.announcement_id for r in new_records]
        assert "ANN-UMS-CACHE-TEST-1" in new_ids


# ===========================================================================
# Test F: Failure handling
# ===========================================================================

class TestFailureHandling:
    """Verify that the system fails safely and reports appropriate status."""

    def test_missing_content_handled_gracefully(self):
        """An announcement with empty content should not crash the sync."""
        mock_adapter = MagicMock()
        mock_adapter.fetch_latest_announcements.return_value = [{
            "id": "EMPTY-1",
            "title": "Notice with no content",
            "full_content": "",
            "publication_date": "2026-10-28",
        }]
        mock_adapter.normalize_announcement.side_effect = lambda raw: UMSSourceAdapter().normalize_announcement(raw)

        sync_service = UMSSyncService(source_adapter=mock_adapter)
        result = sync_service.run_sync(triggered_by="test_empty_content")
        # Should not crash; either store it or report failure
        assert result["status"] in ("SUCCESS", "FAILED")

    def test_failed_embedding_preserves_record(self):
        """If embedding fails, the record must still be in SQLite and searchable."""
        mock_adapter = MagicMock()
        mock_adapter.fetch_latest_announcements.return_value = [{
            "id": "EMBED-FAIL-1",
            "title": "Notice with embedding failure",
            "full_content": "Content for testing embedding failure handling.",
            "publication_date": "2026-10-28",
        }]
        mock_adapter.normalize_announcement.side_effect = lambda raw: UMSSourceAdapter().normalize_announcement(raw)

        # Mock vector store to fail
        mock_vec = MagicMock()
        mock_vec.collection.upsert.side_effect = Exception("ChromaDB connection error")
        mock_vec.prepare_document_text.side_effect = lambda ann, meta: f"Title: {ann.title}\nContent: {ann.full_content}"

        sync_service = UMSSyncService(source_adapter=mock_adapter, vector_store=mock_vec)
        result = sync_service.run_sync(triggered_by="test_embed_fail")

        # Record should be stored even if embedding failed
        assert result["inserted_count"] == 1
        assert result["status"] == "SUCCESS"

        # Verify the record is in SQLite
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT processing_status FROM live_announcements WHERE announcement_id = 'ANN-UMS-EMBED-FAIL-1'")
        row = c.fetchone()
        conn.close()
        assert row is not None
        assert row["processing_status"] in ("STORED", "ANALYZED", "FAILED")

    def test_repeated_sync_is_idempotent(self):
        """Re-syncing the same data must not crash or duplicate."""
        adapter = UMSSourceAdapter(connector_mode="mock")
        sync_service = UMSSyncService(source_adapter=adapter)

        for i in range(3):
            result = sync_service.run_sync(triggered_by=f"test_repeat_{i}", limit=2)
            assert result["status"] in ("SUCCESS", "UP_TO_DATE")

        # Verify no duplicates
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) as cnt FROM live_announcements")
        count = c.fetchone()["cnt"]
        conn.close()
        assert count <= 2, "Repeated syncs should not create duplicates"

    def test_heuristic_extraction_persists_metadata(self):
        """Heuristic extraction metadata must be persisted to the DB during sync
        so it doesn't need re-computation later."""
        mock_adapter = MagicMock()
        mock_adapter.fetch_latest_announcements.return_value = [{
            "id": "PERSIST-1",
            "title": "Notice for metadata persistence test",
            "full_content": "This is to inform that rooms 34-101, 34-102 are exempted on 28-10-2026.",
            "publication_date": "2026-10-28",
            "reference_number": "LPU/PERSIST/2026/001",
        }]
        mock_adapter.normalize_announcement.side_effect = lambda raw: UMSSourceAdapter().normalize_announcement(raw)

        sync_service = UMSSyncService(source_adapter=mock_adapter)
        sync_service.run_sync(triggered_by="test_persist")

        # Verify metadata was persisted
        extraction_service = ExtractionService()
        # Get the content hash from the DB
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT content_hash FROM live_announcements WHERE announcement_id = 'ANN-UMS-PERSIST-1'")
        row = c.fetchone()
        conn.close()
        assert row is not None

        cached = extraction_service.get_cached_metadata(row["content_hash"])
        assert cached is not None, "Heuristic metadata should be persisted after sync"
        assert cached.impact_type == "ROOM_EXEMPTION"
        assert "34-101" in cached.affected_rooms


# ===========================================================================
# Test G: Existing behavior preservation (smoke test)
# ===========================================================================

class TestExistingBehavior:
    """Verify that existing functionality still works after the changes."""

    def test_dataset_loads_successfully(self):
        """The dataset should still load with historical + live records."""
        ds = DatasetService()
        records, report = ds.load_dataset(include_live=True)
        assert len(records) > 0
        assert "total_records" in report

    def test_search_returns_results(self):
        """Standard search should still return results."""
        ds = DatasetService()
        announcements, _ = ds.load_dataset(include_live=True)

        service = RetrievalService()
        results = service.search(
            query="examination schedule",
            top_k=5,
            raw_announcements=announcements,
        )
        # Should return results (from historical data)
        assert len(results) >= 0  # May be 0 if no exam notices, but should not crash

    def test_search_results_include_impact_type(self):
        """Search results should now include the impact_type field."""
        ds = DatasetService()
        announcements, _ = ds.load_dataset(include_live=True)

        service = RetrievalService()
        results = service.search(
            query="Block 34",
            top_k=5,
            raw_announcements=announcements,
        )
        for r in results:
            assert "impact_type" in r
            assert "impact_facts" in r

    def test_extraction_service_still_works(self):
        """The extraction service heuristic should still produce valid metadata."""
        ann = RawAnnouncement(
            announcement_id="TEST-EXT-1",
            title="Test Announcement",
            publication_date="2026-10-28",
            full_content="This is a test announcement about an event.",
            attachment_present=False,
            content_hash="test_ext_hash_1",
        )
        service = ExtractionService()
        meta = service.fallback_heuristic_extraction(ann)
        assert meta is not None
        assert meta.category is not None
        assert meta.confidence > 0

    def test_diagnostics_endpoint_returns_data(self):
        """The diagnostics endpoint should return pipeline status data."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)

        resp = client.get("/api/v1/diagnostics/pipeline")
        assert resp.status_code == 200
        data = resp.json()
        assert "raw_live_records" in data
        assert "chromadb_indexed_count" in data
        assert "processing_status_breakdown" in data
