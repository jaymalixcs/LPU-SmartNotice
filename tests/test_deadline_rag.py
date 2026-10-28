"""Regression and Unit tests for Deadline Retrieval, Query Normalization, and RAG Grounding.

Tests cover:
1. Synthetic announcement with accommodation details is retrieved by exact question.
2. Synonyms ("residential address", "PG details", "accommodation details") retrieve the notice.
3. Raw announcements can be found lexically even when absent from ChromaDB.
4. Irrelevant newer room-allocation announcements do not displace the relevant deadline announcement.
5. Response distinguishes publication date (22 Oct) from actual deadline (26 Oct).
6. Source reference returned matches the retrieved announcement.
7. Missing announcement results in insufficient evidence statement rather than fabrication.
8. Cache invalidation and index reconciliation work correctly.
"""

from unittest.mock import MagicMock, patch
import pytest

from app.models.announcement import RawAnnouncement
from app.models.chat import ChatRequest
from app.services.chat_service import ChatService
from app.services.dataset_service import DatasetService
from app.services.retrieval_service import RetrievalService, normalize_query_text
from app.services.vector_store_service import VectorStoreService


@pytest.fixture
def accommodation_notice():
    return RawAnnouncement(
        announcement_id="ANN-TEST-ACCOMMODATION-001",
        title="MANDATORY VERIFICATION- Student PG/Residential Address Details",
        publication_date="10/22/2026",
        reference_number="LPU/10.2/ANN/2024/023/IC/261022/0086",
        full_content=(
            "Dear Students,\n"
            "As required by the authorities, all students residing outside the University campus "
            "are mandatorily required to verify and confirm their current PG/residential details immediately.\n"
            "Please update or confirm your details using the link below:\n"
            "Open LPU Touch App--- Open Side Menu--- Click on Accommodation Details\n"
            "Students are advised to treat this as an urgent and compulsory activity and complete the verification without delay. "
            "The last date to fill in the details is 26th October 2026 (Monday).\n\n"
            "Uploaded By:\nOffice of HOD\nOffice of Academic Services"
        ),
        attachment_present=False,
        attachment_names=[],
        content_hash="hash_accommodation_001",
        source="ums"
    )


@pytest.fixture
def room_allocation_notice():
    return RawAnnouncement(
        announcement_id="ANN-TEST-ROOM-002",
        title="14106, 14312, 14313, 14414, 14415",
        publication_date="2026-10-27",
        reference_number="UMS-ROW-4",
        full_content="Block 14 Rooms 14106, 14312, 14313, 14414, 14415. Exempted Until 11:00 AM, 27th October 2026.",
        attachment_present=False,
        attachment_names=[],
        content_hash="hash_room_002",
        source="ums"
    )


def test_synthetic_notice_retrieved_by_exact_question(accommodation_notice, room_allocation_notice):
    """1. Synthetic announcement is retrieved at rank 1 by exact student query."""
    retrieval_service = RetrievalService()
    # Mock ChromaDB returning empty to test robust candidate retrieval
    with patch.object(retrieval_service.vector_store.collection, "count", return_value=0):
        results = retrieval_service.search(
            query="When was the last date to fill the accommodation details?",
            top_k=5,
            raw_announcements=[accommodation_notice, room_allocation_notice]
        )

    assert len(results) > 0
    top_result = results[0]
    assert top_result["announcement_id"] == accommodation_notice.announcement_id
    assert "MANDATORY VERIFICATION" in top_result["title"]
    assert top_result["reference_number"] == "LPU/10.2/ANN/2024/023/IC/261022/0086"


def test_synonym_queries_retrieve_relevant_notice(accommodation_notice, room_allocation_notice):
    """2. Natural language synonyms and common typos all retrieve the accommodation notice."""
    retrieval_service = RetrievalService()
    queries = [
        "residential address deadline",
        "What is the last date to update PG details?",
        "When was the last date to fill the accommodation details?",
        "when was the last date to fill the accoummodation details",  # typo with double m
        "due date for residential verification",
        "final date to confirm accommodation details"
    ]

    with patch.object(retrieval_service.vector_store.collection, "count", return_value=0):
        for q in queries:
            results = retrieval_service.search(
                query=q,
                top_k=5,
                raw_announcements=[accommodation_notice, room_allocation_notice]
            )
            assert len(results) > 0, f"Failed for query: {q}"
            top_ids = [r["announcement_id"] for r in results]
            assert accommodation_notice.announcement_id in top_ids, f"Target notice missing for query: {q}"
            assert results[0]["announcement_id"] == accommodation_notice.announcement_id, f"Target notice was not #1 for query: {q}"


def test_lexical_search_finds_notice_absent_from_chromadb(accommodation_notice):
    """3. An announcement can be found through lexical search even when completely absent from ChromaDB."""
    retrieval_service = RetrievalService()

    with patch.object(retrieval_service.vector_store.collection, "count", return_value=0):
        results = retrieval_service.search(
            query="LPU/10.2/ANN/2024/023/IC/261022/0086",
            top_k=3,
            raw_announcements=[accommodation_notice]
        )

    assert len(results) == 1
    assert results[0]["announcement_id"] == accommodation_notice.announcement_id
    assert results[0]["semantic_score"] == 0.0  # purely lexical retrieval


def test_newer_room_allocation_does_not_displace_deadline_notice(accommodation_notice, room_allocation_notice):
    """4. An irrelevant newer room-allocation announcement does not displace the relevant deadline announcement."""
    retrieval_service = RetrievalService()

    # Even if ChromaDB has the room allocation notice embedded, lexical/RRF should rank accommodation notice #1
    mock_chroma_res = {
        "ids": [[room_allocation_notice.announcement_id]],
        "documents": [[room_allocation_notice.full_content]],
        "metadatas": [[{"announcement_id": room_allocation_notice.announcement_id, "title": room_allocation_notice.title}]],
        "distances": [[0.6]]
    }

    with patch.object(retrieval_service.vector_store.collection, "count", return_value=1), \
         patch.object(retrieval_service.vector_store.collection, "query", return_value=mock_chroma_res), \
         patch.object(retrieval_service.embedding_service, "embed_text", return_value=[0.1] * 768):

        results = retrieval_service.search(
            query="When was the last date to fill the accommodation details?",
            top_k=5,
            raw_announcements=[room_allocation_notice, accommodation_notice]
        )

    assert len(results) >= 1
    assert results[0]["announcement_id"] == accommodation_notice.announcement_id
    # The room notice should have a much lower rank or score
    if len(results) > 1:
        assert results[0]["rrf_score"] >= results[1]["rrf_score"]


def test_response_distinguishes_publication_date_from_deadline(accommodation_notice):
    """5. The generated response distinguishes the publication date (22 Oct) from the actual deadline (26 Oct)."""
    chat_service = ChatService()
    req = ChatRequest(query="When was the last date to fill the accommodation details?")

    expected_llm_text = (
        "The last date to fill in your accommodation/PG-residential address details was 26 October 2026 (Monday). "
        "The notice was published on 22 October 2026 and instructed students residing outside the university campus "
        "to verify their current residential details through LPU Touch App → Side Menu → Accommodation Details. "
        "Source: MANDATORY VERIFICATION- Student PG/Residential Address Details, reference LPU/10.2/ANN/2024/023/IC/261022/0086. "
        "[Source ID: ANN-TEST-ACCOMMODATION-001]"
    )

    mock_response = MagicMock()
    mock_response.text = expected_llm_text

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch.object(chat_service, "get_client", return_value=mock_client), \
         patch.object(chat_service.retrieval_service.vector_store.collection, "count", return_value=0):

        response = chat_service.answer_question(req, raw_announcements=[accommodation_notice])

    assert "26 October 2026" in response.answer or "26th October 2026" in response.answer
    assert "22 October 2026" in response.answer or "10/22/2026" in response.answer
    assert not response.insufficient_evidence
    assert len(response.sources) == 1
    assert response.sources[0].reference_number == "LPU/10.2/ANN/2024/023/IC/261022/0086"


def test_source_reference_matches_retrieved_announcement(accommodation_notice):
    """6. The source reference returned to the student matches the retrieved announcement."""
    chat_service = ChatService()
    req = ChatRequest(query="When was the last date to fill the accommodation details?")

    mock_response = MagicMock()
    mock_response.text = "The deadline was 26 October 2026 [Source ID: ANN-TEST-ACCOMMODATION-001]."
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch.object(chat_service, "get_client", return_value=mock_client), \
         patch.object(chat_service.retrieval_service.vector_store.collection, "count", return_value=0):

        res = chat_service.answer_question(req, raw_announcements=[accommodation_notice])

    assert len(res.sources) == 1
    src = res.sources[0]
    assert src.announcement_id == "ANN-TEST-ACCOMMODATION-001"
    assert src.title == "MANDATORY VERIFICATION- Student PG/Residential Address Details"
    assert src.reference_number == "LPU/10.2/ANN/2024/023/IC/261022/0086"
    assert src.publication_date == "10/22/2026"


def test_insufficient_evidence_when_announcement_missing(room_allocation_notice):
    """7. If the source announcement is missing from storage, the chatbot reports insufficient evidence without fabricating."""
    chat_service = ChatService()
    req = ChatRequest(query="When was the last date to fill the accommodation details?")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Based on the available university announcements, no records were found regarding accommodation details."
    mock_client.models.generate_content.return_value = mock_response

    # Provide only room allocation notice (which has 0 lexical score for accommodation)
    with patch.object(chat_service, "get_client", return_value=mock_client), \
         patch.object(chat_service.retrieval_service.vector_store.collection, "count", return_value=0):

        res = chat_service.answer_question(req, raw_announcements=[room_allocation_notice])

    # Since room notice has score 0 for accommodation query, candidate list should be empty
    assert res.insufficient_evidence is True
    assert "could not find any relevant university announcements" in res.answer.lower()


def test_cache_invalidation_and_index_reconciliation():
    """8. Cache invalidation properly resets cached records, and diagnostics report completeness correctly."""
    DatasetService.clear_cache()
    assert DatasetService._cached_records is None
    assert DatasetService._cached_report is None

    vs = VectorStoreService()
    # Mock collection
    mock_coll = MagicMock()
    mock_coll.count.return_value = 50
    mock_coll.get.return_value = {"ids": [f"ID-{i}" for i in range(50)]}

    synthetic_records = [
        RawAnnouncement(
            announcement_id=f"ID-{i}",
            title=f"Notice {i}",
            publication_date="2026-10-01",
            reference_number=f"REF-{i}",
            full_content=f"Content {i}"
        )
        for i in range(100)
    ]

    with patch.object(vs, "collection", mock_coll):
        diag = vs.get_detailed_index_diagnostics(announcements=synthetic_records)
        assert diag["total_corpus_records"] == 100
        assert diag["total_indexed_documents"] == 50
        assert diag["coverage_percentage"] == 50.0
        assert diag["missing_from_index_count"] == 50
        assert len(diag["sample_missing_ids"]) <= 10

