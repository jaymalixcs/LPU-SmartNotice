import os
import re
import time
from typing import List, Dict, Any, Optional
from google import genai
from google.genai import types

from app.core.config import settings
from app.core.logging_config import logger
from app.core.security import validate_api_key_configured
from app.models.chat import (
    ChatRequest,
    ChatResponse,
    AnnouncementSourceReference,
    ChatMessage
)
from app.services.retrieval_service import RetrievalService
from app.models.announcement import RawAnnouncement
from app.services.temporal_service import build_temporal_prompt_context
from app.services.impact_classifier import is_location_impact_query


def is_conversational_greeting(query: str) -> bool:
    """Check if query is a simple greeting or chitchat without specific announcement requests."""
    q = query.strip().lower()
    topic_keywords = {
        "exam", "examination", "schedule", "placement", "drive", "interview",
        "company", "room", "class", "block", "timetable", "date", "fee", "fees",
        "scholarship", "hostel", "holiday", "attendance", "result", "grade",
        "cgpa", "eligibility", "convocation", "registration", "deadline", "event",
        "who", "what", "where", "when", "why", "how", "course"
    }
    words = set(re.findall(r"\w+", q))
    # If any specific topic is mentioned (except question words alone), it's not just a greeting
    if words.intersection(topic_keywords - {"who", "what", "where", "when", "why", "how"}):
        return False

    greeting_patterns = [
        r"^(hi|hello|hey|heya|howdy|greetings|hola)\b",
        r"^good\s+(morning|afternoon|evening|day)\b",
        r"^who\s+are\s+you\b",
        r"^what\s+(is\s+your\s+name|can\s+you\s+do)\b",
        r"^help(\s+me)?\b",
    ]
    for pattern in greeting_patterns:
        if re.search(pattern, q):
            return True
    return False


class ChatService:
    """Grounded RAG Chatbot Service with attachment-awareness, history, and citation verification."""

    def __init__(self):
        self.retrieval_service = RetrievalService()

    def get_client(self) -> genai.Client:
        key = settings.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY", "")
        if not key or key == "your_gemini_api_key_here":
            raise ValueError("GEMINI_API_KEY is not configured in .env file.")
        return genai.Client(api_key=key, http_options=types.HttpOptions(timeout=60000))

    def answer_question(
        self,
        request: ChatRequest,
        raw_announcements: Optional[List[RawAnnouncement]] = None
    ) -> ChatResponse:
        """Process natural language question using grounded RAG pipeline."""
        start_time = time.time()
        query = request.query.strip()

        # Check for polite greeting / chitchat first
        if is_conversational_greeting(query):
            greeting_answer = (
                "Hello! I am your LPU SmartNotice AI Assistant. "
                "I can answer questions grounded in official Lovely Professional University announcements, "
                "such as examination schedules, placement drives, scholarship notices, room changes, "
                "and important deadlines. How can I assist you today?"
            )
            return ChatResponse(
                answer=greeting_answer,
                sources=[],
                attachment_warning=None,
                insufficient_evidence=False,
                processing_time_ms=int((time.time() - start_time) * 1000)
            )

        # Determine effective top_k (expand for comprehensive lists like rooms/today/all)
        q_lower = query.lower()
        is_broad_query = any(w in q_lower for w in ["room", "exempt", "block", "class", "today", "timetable", "list", "all"])
        effective_top_k = max(request.top_k, 15) if is_broad_query else request.top_k

        # Detect location-impact intent (e.g. "What announcements affect Block 34?")
        location_impact = is_location_impact_query(query)

        # 1. Retrieve Announcement Evidence safely
        impact_categories: Optional[Dict[str, List[Dict[str, Any]]]] = None
        try:
            if location_impact:
                impact_result = self.retrieval_service.search_location_impact(
                    query=query,
                    top_k=effective_top_k,
                    raw_announcements=raw_announcements,
                )
                candidates = impact_result.get("results", [])
                impact_categories = impact_result.get("categories")
            else:
                candidates = self.retrieval_service.search(
                    query=query,
                    top_k=effective_top_k,
                    raw_announcements=raw_announcements
                )
        except Exception as ret_err:
            logger.error("Announcement retrieval failed: %s", ret_err)
            candidates = []

        sources: List[AnnouncementSourceReference] = []
        attachment_warnings: List[str] = []
        evidence_text_blocks: List[str] = []

        if not candidates:
            answer = "I could not find any relevant university announcements in the database to answer your question."
            return ChatResponse(
                answer=answer,
                sources=[],
                attachment_warning=None,
                insufficient_evidence=True,
                processing_time_ms=int((time.time() - start_time) * 1000)
            )

        for cand in candidates:
            raw_att = cand.get("attachment_names", [])
            if isinstance(raw_att, list):
                att_names = [str(x) for x in raw_att if str(x).strip()]
            else:
                att_names = [x.strip() for x in str(raw_att).split(",") if x.strip()]

            sources.append(
                AnnouncementSourceReference(
                    announcement_id=cand["announcement_id"],
                    title=cand["title"],
                    reference_number=cand.get("reference_number"),
                    publication_date=cand["publication_date"],
                    similarity_score=cand.get("rrf_score", 0.0),
                    attachment_present=cand["attachment_present"],
                    attachment_names=att_names,
                    attachment_content_available=False,
                    decision_completeness=cand["decision_completeness"],
                    source=cand.get("source", "historical"),
                    source_url=cand.get("source_url")
                )
            )

            if cand["attachment_present"]:
                names_str = ", ".join(att_names) if att_names else "attached file"
                attachment_warnings.append(
                    f"Notice '{cand['title']}' references attachment ({names_str}), but attachment file contents are unavailable."
                )

            active_dates_str = ", ".join(cand.get("notice_dates", [])) or cand["publication_date"]
            if cand.get("matches_target_date") is True:
                target_match_str = "YES (Applies to requested date)"
            elif cand.get("matches_target_date") is False:
                target_match_str = "NO / DIFFERENT DATE"
            else:
                target_match_str = "GENERAL / DEADLINE NOTICE"

            # Include structured impact classification in the evidence
            impact_type = cand.get("impact_type", "UNKNOWN_IMPACT")
            impact_facts = cand.get("impact_facts", {})
            impact_line = f"Impact Classification: {impact_type}"
            if impact_facts.get("block"):
                impact_line += f" | Block: {impact_facts['block']}"
            if impact_facts.get("affected_rooms"):
                impact_line += f" | Affected Rooms: {', '.join(impact_facts['affected_rooms'])}"
            if impact_facts.get("event_date"):
                impact_line += f" | Event Date: {impact_facts['event_date']}"
            if impact_facts.get("start_time"):
                impact_line += f" | Time: {impact_facts['start_time']} - {impact_facts.get('end_time', 'N/A')}"
            if impact_facts.get("source_evidence"):
                impact_line += f" | Evidence: {impact_facts['source_evidence'][:150]}"

            evidence_text_blocks.append(
                f"[Source ID: {cand['announcement_id']}]\n"
                f"Title: {cand['title']}\n"
                f"Publication Date: {cand['publication_date']}\n"
                f"Active/Governing Dates: {active_dates_str}\n"
                f"Matches Target Date: {target_match_str}\n"
                f"Reference #: {cand.get('reference_number') or 'N/A'}\n"
                f"Has Attachment: {cand['attachment_present']} ({', '.join(att_names) if att_names else 'None'})\n"
                f"{impact_line}\n"
                f"Content: {cand['document']}\n"
            )

        # Build categorized evidence for location-impact queries
        categorized_evidence = ""
        if impact_categories and location_impact:
            cat_labels = {
                "ROOM_EXEMPTION": "ROOMS EXEMPTED OR UNAVAILABLE",
                "ROOM_UNAVAILABLE": "ROOMS UNAVAILABLE",
                "BLOCK_RESTRICTION": "BUILDING/BLOCK RESTRICTIONS",
                "CLASS_CANCELLATION": "CLASS CANCELLATIONS",
                "VENUE_CHANGE": "VENUE CHANGES",
                "EVENT_LOCATION": "EVENTS TAKING PLACE (NOT EXEMPTIONS)",
                "ROOM_MENTION_ONLY": "OTHER NOTICES MENTIONING THE LOCATION",
                "UNKNOWN_IMPACT": "OTHER RELEVANT NOTICES",
            }
            cat_parts = []
            for cat, items in impact_categories.items():
                if not items:
                    continue
                label = cat_labels.get(cat, cat)
                cat_parts.append(f"\n=== {label} ({len(items)} notice(s)) ===")
                for item in items:
                    impact = item.get("impact_facts", {})
                    rooms_str = ", ".join(impact.get("affected_rooms", [])) or "N/A"
                    date_str = impact.get("event_date") or item.get("publication_date", "N/A")
                    time_str = ""
                    if impact.get("start_time"):
                        time_str = f" {impact['start_time']}-{impact.get('end_time', 'N/A')}"
                    cat_parts.append(
                        f"  - [{item['announcement_id']}] {item['title']}\n"
                        f"    Rooms: {rooms_str} | Date: {date_str}{time_str}\n"
                        f"    Ref: {item.get('reference_number') or 'N/A'} | Published: {item.get('publication_date', 'N/A')}"
                    )
            if cat_parts:
                categorized_evidence = "\n\nSTRUCTURED IMPACT CATEGORIES:\n" + "\n".join(cat_parts)

        combined_evidence = "\n---\n".join(evidence_text_blocks)
        if categorized_evidence:
            combined_evidence += categorized_evidence

        # Build Multi-Turn History Context
        history_context = ""
        if request.history:
            recent_turns = request.history[-6:]
            formatted_turns = []
            for msg in recent_turns:
                role_label = "Student" if msg.role == "user" else "Assistant"
                turn_content = msg.content.strip()
                if len(turn_content) > 300:
                    turn_content = turn_content[:300] + "..."
                formatted_turns.append(f"{role_label}: {turn_content}")
            history_context = "Previous Conversation Context:\n" + "\n".join(formatted_turns) + "\n\n"

        student_context = f"\nActive Student Context: Student ID {request.student_id}\n" if request.student_id else ""
        temporal_info = build_temporal_prompt_context(query)

        # 2. Build Grounded Prompt for Gemini API
        prompt = f"""You are LPU SmartNotice AI Assistant. Your task is to answer the student's question strictly, accurately, and faithfully based ONLY on the retrieved university announcement evidence provided below.

CURRENT CALENDAR & TEMPORAL CONTEXT:
- Current Reference Date: {temporal_info['today_name']}, {temporal_info['today_human']} (ISO: {temporal_info['today_iso']})
- Tomorrow: {temporal_info['tomorrow_name']}, {temporal_info['tomorrow_human']} (ISO: {temporal_info['tomorrow_iso']})
- Yesterday: {temporal_info['yesterday_name']}, {temporal_info['yesterday_human']} (ISO: {temporal_info['yesterday_iso']})
- Student Requested Timeframe: {temporal_info['requested_context']}

STRICT GROUNDING & TEMPORAL VERIFICATION RULES:
1. Base your answer ONLY on the retrieved announcement evidence provided below.
2. DATE VERIFICATION & TEMPORAL INTEGRITY:
   - When the student asks about a specific date or timeframe (e.g., "today", "tomorrow", or an explicit date): verify whether each announcement actually governs the requested timeframe: {temporal_info['requested_context']}.
   - Check BOTH the publication date AND the dates/timings explicitly stated in the announcement text.
   - If an announcement specifies a different or past date and does NOT govern the requested date, DO NOT report its rooms/events as applicable to the requested date.
3. DEADLINE & LAST DATE QUERIES (CRITICAL):
   - When asked for a deadline, last date, due date, or timeline:
     (a) Distinguish clearly between the Announcement Publication Date (when the notice was uploaded/issued) and the Action Deadline (the date by which students must complete the activity).
     (b) State the exact deadline date and day (e.g., "26 October 2026 (Monday)") as specified in the announcement.
     (c) State the publication date (e.g., "published on 22 October 2026").
     (d) State the action instructed in the notice (e.g., steps in LPU Touch App or portal).
     (e) Cite the official announcement Title, Reference Number, and [Source ID: ...].
     (f) If the question is about a specific subject (such as accommodation or residential address), do NOT substitute or cite unrelated room-allocation notices or other deadlines.
4. ROOM/BLOCK IMPACT QUERIES (CRITICAL — DO NOT MIX CATEGORIES):
   - When asked "What announcements affect Block X?" or similar location-impact questions, you MUST categorize your answer by impact type. These categories are NOT interchangeable:
     (a) ROOMS EXEMPTED/UNAVAILABLE: Notices that explicitly exempt or close rooms (e.g., "the following BYOD Rooms are exempted on [date] from [time] to [time]"). List exact room numbers, date, and time window. These are the primary actionable results.
     (b) BLOCK/BUILDING RESTRICTIONS: Notices restricting access to a building (e.g., "entry is prohibited in Building 34"). State scope and date.
     (c) CLASS CANCELLATIONS: Notices cancelling specific classes. State which classes and dates.
     (d) VENUE CHANGES: Notices moving a class or exam to a different room. State old and new rooms.
     (e) EVENTS TAKING PLACE: Notices where an event is merely SCHEDULED in a room (e.g., "workshop will be held in Block 34-413"). These are NOT exemptions. Clearly label them as events, NOT room exemptions. A room hosting an event is NOT the same as a room being exempted.
     (f) OTHER MENTIONS: Notices that merely mention a block/room without changing its availability. Include only if genuinely relevant; clearly state they do NOT indicate room unavailability.
   - Use the "Impact Classification" line in each evidence block and the "STRUCTURED IMPACT CATEGORIES" section to determine the correct category.
   - NEVER present an event location as a room exemption, and never present a room exemption as an event.
   - If no room exemption notices exist for the queried block, state that clearly rather than substituting event-location notices.
   - Group exempted rooms by Block number and state the exact room numbers and time window.
5. CITATIONS: Every factual claim, room group, or notice detail MUST cite its Source ID in brackets, e.g. [Source ID: ANN-...], along with reference number when available.
6. INSUFFICIENT EVIDENCE:
   - If the student asked about a specific date and no matching announcement exists, state: "Based on available announcements for this date, no records were found."
   - If the student asked about a specific topic/deadline and no relevant announcement exists in the evidence, state clearly: "Based on the available university announcements, no records were found regarding [topic]."
   - Do NOT fabricate dates, room numbers, policies, or sources.
7. ATTACHMENT NOTICE: If an announcement references an attachment whose internal contents are unavailable, state that the attachment is referenced but its internal contents are unavailable. Never pretend to know unprovided attachment content.
{student_context}
{history_context}Retrieved Announcement Evidence:
{combined_evidence}

Student Question:
{query}
"""

        if not validate_api_key_configured():
            # Return grounded fallback answer if API key missing
            fallback_text = f"Based on retrieved evidence ({len(sources)} sources):\n"
            for src in sources:
                fallback_text += f"• [{src.announcement_id}] {src.title} ({src.publication_date})\n"
            fallback_text += "\n(Note: Full AI generation disabled because GEMINI_API_KEY is not configured.)"
            return ChatResponse(
                answer=fallback_text,
                sources=sources,
                attachment_warning="; ".join(attachment_warnings) if attachment_warnings else None,
                insufficient_evidence=False,
                processing_time_ms=int((time.time() - start_time) * 1000)
            )

        try:
            client = self.get_client()
            response = None
            candidate_models = [
                settings.GEMINI_GENERATION_MODEL,
                "gemini-flash-lite-latest",
                "gemini-3.5-flash",
                "gemini-3.5-flash-lite",
                "gemini-3-flash-preview",
            ]
            # Deduplicate preserving order
            seen_models = set()
            models_to_try = [m for m in candidate_models if m and not (m in seen_models or seen_models.add(m))]

            last_gen_err = None
            for m_name in models_to_try:
                try:
                    response = client.models.generate_content(
                        model=m_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(temperature=0.2),
                    )
                    if response and response.text:
                        break
                except Exception as gen_err:
                    last_gen_err = gen_err
                    logger.warning("Generation attempt with '%s' failed: %s; trying fallback...", m_name, gen_err)

            if response is None or not response.text:
                if last_gen_err:
                    raise last_gen_err
                raise RuntimeError("All candidate models failed to return a response.")
            answer_text = response.text or "No response generated."
            processing_ms = int((time.time() - start_time) * 1000)

            return ChatResponse(
                answer=answer_text,
                sources=sources,
                attachment_warning="; ".join(attachment_warnings) if attachment_warnings else None,
                insufficient_evidence=False,
                processing_time_ms=processing_ms
            )

        except Exception as e:
            logger.error("Chat generation failed: %s", e)
            error_str = str(e)
            if "RESOURCE_EXHAUSTED" in error_str or "quota" in error_str.lower():
                user_msg = "The AI service is currently experiencing high demand (quota limit reached). Here are the relevant announcements found in the database:"
            elif "timed out" in error_str.lower() or "timeout" in error_str.lower():
                user_msg = "The AI response timed out. Here are the relevant announcements retrieved for your query:"
            else:
                user_msg = "I encountered an error generating the natural language response. Here are the relevant announcements retrieved for your query:"

            fallback_text = f"{user_msg}\n\n"
            for src in sources:
                fallback_text += f"• [{src.announcement_id}] {src.title} ({src.publication_date})\n"

            return ChatResponse(
                answer=fallback_text,
                sources=sources,
                attachment_warning="; ".join(attachment_warnings) if attachment_warnings else None,
                insufficient_evidence=False,
                processing_time_ms=int((time.time() - start_time) * 1000)
            )
