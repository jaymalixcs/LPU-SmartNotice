"""Deterministic Impact Classification for LPU Announcements.

Classifies room/block related notices into structured impact categories and
extracts the factual evidence supporting each classification. This module is
intentionally regex-driven and deterministic so it works offline without any
LLM API call. It can be used as a fast heuristic fallback and as structured
metadata enrichment for the retrieval/RAG pipeline.

Impact categories (not interchangeable):
    ROOM_EXEMPTION      - rooms explicitly exempted/unavailable for a period
    ROOM_UNAVAILABLE    - rooms closed/locked/out of service
    BLOCK_RESTRICTION   - building or block access restricted
    CLASS_CANCELLATION  - specific classes cancelled (not whole room)
    VENUE_CHANGE        - class or event moved to a new room
    EVENT_LOCATION      - an event is merely *taking place* in a room/block
    ROOM_MENTION_ONLY   - notice mentions a room without changing availability
    UNKNOWN_IMPACT      - cannot determine from the text
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple

from app.core.logging_config import logger

# ---------------------------------------------------------------------------
# Room-number parsing helpers
# ---------------------------------------------------------------------------

# Full "block-room" format: 34-301, 34-301A, 34-304X
_RE_FULL_ROOM = re.compile(r"\b(\d{1,2})-(\d{3}[A-Za-z]?)\b")

# 5-digit LPU compact notation: 34304X, 14106, 26304Y
_RE_COMPACT_ROOM = re.compile(r"\b(\d{2})(\d{3}[A-Za-z]?)\b")

# "Block 34 Room 413" / "Block 34, Room 413"
_RE_BLOCK_ROOM = re.compile(r"block\s*(\d{1,2})[^\d]*room\s*(\d{3}[A-Za-z]?)", re.IGNORECASE)

# "Venue: Block 34-413" or "Venue: Block 34-604"
_RE_VENUE_BLOCK_ROOM = re.compile(r"venue\s*:?\s*block\s*(\d{1,2})[-\s]*(\d{3}[A-Za-z]?)", re.IGNORECASE)

# Room range: "34-101 to 34-110" or "34-101 - 34-110"
_RE_ROOM_RANGE = re.compile(r"(\d{1,2})-(\d{3}[A-Za-z]?)\s*(?:to|-|through|–)\s*(\d{1,2})-(\d{3}[A-Za-z]?)", re.IGNORECASE)

# Compressed room list after a block prefix: "34-111, 213, 413" → 34-111, 34-213, 34-413
_RE_COMPRESSED_LIST = re.compile(r"(\d{1,2})-(\d{3}[A-Za-z]?)\s*,\s*((?:\d{3}[A-Za-z]?\s*,?\s*)+)")


def _normalize_room_token(block: str, room: str) -> str:
    """Return canonical 'BLOCK-ROOM' uppercased string."""
    return f"{int(block)}-{room.upper()}"


def parse_room_list(text: str) -> List[str]:
    """Extract all canonical block-room identifiers from arbitrary text.

    Handles:
      - Full format: 34-301, 34-301A
      - Compact 5-digit: 34304X
      - "Block 34 Room 413"
      - "Venue: Block 34-413"
      - Ranges: 34-101 to 34-110
      - Compressed lists: 34-111, 213, 413  →  34-111, 34-213, 34-413
    """
    if not text:
        return []

    rooms: List[str] = []
    seen = set()

    def _add(room: str) -> None:
        if room and room not in seen:
            seen.add(room)
            rooms.append(room)

    # 1. Compressed lists: "34-111, 213, 413" → expand prefix
    for m in _RE_COMPRESSED_LIST.finditer(text):
        block = m.group(1)
        first_room = m.group(2)
        rest = m.group(3)
        _add(_normalize_room_token(block, first_room))
        for rm in re.findall(r"\d{3}[A-Za-z]?", rest):
            _add(_normalize_room_token(block, rm))

    # 2. Ranges: "34-101 to 34-110"
    for m in _RE_ROOM_RANGE.finditer(text):
        b1, r1, b2, r2 = m.group(1), m.group(2), m.group(3), m.group(4)
        if b1 == b2 and r1.isdigit() and r2.isdigit():
            start_n, end_n = int(r1), int(r2)
            if start_n <= end_n and (end_n - start_n) <= 50:
                for n in range(start_n, end_n + 1):
                    _add(_normalize_room_token(b1, f"{n:03d}"))
            continue  # range consumed; don't double-add endpoints

    # 3. Full format: 34-301
    for m in _RE_FULL_ROOM.finditer(text):
        _add(_normalize_room_token(m.group(1), m.group(2)))

    # 4. "Block 34 Room 413"
    for m in _RE_BLOCK_ROOM.finditer(text):
        _add(_normalize_room_token(m.group(1), m.group(2)))

    # 5. "Venue: Block 34-413"
    for m in _RE_VENUE_BLOCK_ROOM.finditer(text):
        _add(_normalize_room_token(m.group(1), m.group(2)))

    # 6. Compact 5-digit: 34304X  (only if not already captured by full format)
    #    Be conservative: only match 5-digit numbers that appear near room-related context
    #    to avoid false positives from reference numbers like "24990" or "63608".
    for m in _RE_COMPACT_ROOM.finditer(text):
        # Check context: the 5-digit number should be near room/lab/block keywords
        # or be part of a room list, not inside a reference number pattern
        start = max(0, m.start() - 30)
        context = text[start:m.end() + 10].lower()
        # Skip if it looks like a reference number (preceded by TC./OC./LPU/ etc.)
        before = text[max(0, m.start() - 5):m.start()]
        if re.search(r'[A-Z]{2}\.\d', before):
            continue
        # Only accept if near room context keywords
        if any(kw in context for kw in ["room", "lab", "block", "venue", "byod", "class", "exempt"]):
            _add(_normalize_room_token(m.group(1), m.group(2)))

    return rooms


def extract_block_numbers(text: str) -> List[str]:
    """Extract block/building numbers mentioned in text (e.g. ['34', '27'])."""
    if not text:
        return []
    # "Block 34", "Building 34", "Block-34"
    blocks = re.findall(r"(?:block|building)\s*(\d{1,2})\b", text, re.IGNORECASE)
    # Deduplicate preserving order
    seen = set()
    result = []
    for b in blocks:
        if b not in seen:
            seen.add(b)
            result.append(b)
    return result


# ---------------------------------------------------------------------------
# Date / time extraction
# ---------------------------------------------------------------------------

MONTH_MAP = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def _parse_date_string(s: str, default_year: int = 2026) -> Optional[str]:
    """Parse a date fragment into ISO YYYY-MM-DD. Returns None if unparseable."""
    s = s.strip()
    # ISO
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        try:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        except ValueError:
            pass
    # DD-MM-YYYY or DD/MM/YYYY
    m = re.match(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", s)
    if m:
        d, mo, y = m.groups()
        try:
            return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        except ValueError:
            pass
    # "28th September 2026" / "28 Sep 2026"
    m = re.match(r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)\s+(\d{4})", s, re.IGNORECASE)
    if m:
        d, mo_str, y = m.groups()
        mo = MONTH_MAP.get(mo_str[:3].lower())
        if mo:
            try:
                return f"{int(y):04d}-{mo:02d}-{int(d):02d}"
            except ValueError:
                pass
    return None


def extract_event_date(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract the event/governing date and the original evidence phrase.

    Looks for patterns like "exempted on 28-09-2026", "on 22-09-2026",
    "Date: 24th September, 2026".
    Returns (iso_date, evidence_phrase).
    """
    if not text:
        return None, None

    # "exempted on <date>" / "exempted from <date>"
    m = re.search(
        r"(?:exempted|closed|suspended|cancelled|conducted|held|scheduled)\s+(?:on|from)\s+(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}(?:st|nd|rd|th)?\s+[a-z]+\s*,?\s*\d{4})",
        text, re.IGNORECASE,
    )
    if m:
        iso = _parse_date_string(m.group(1))
        if iso:
            return iso, m.group(0).strip()

    # "Date: 24th September, 2026"
    m = re.search(r"date\s*:?\s*(\d{1,2}(?:st|nd|rd|th)?\s+[a-z]+\s*,?\s*\d{4})", text, re.IGNORECASE)
    if m:
        iso = _parse_date_string(m.group(1))
        if iso:
            return iso, m.group(0).strip()

    # Standalone ISO date in text
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if m:
        return m.group(1), m.group(0)

    return None, None


def extract_time_window(text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract start time, end time, and the original evidence phrase.

    Handles "from 10 AM to 2 PM", "between 9:00 AM and 7:00 PM",
    "from 11 am to 5 pm", "10:00 AM - 01:00 PM".
    """
    if not text:
        return None, None, None

    time_pat = r"(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM))"

    # "from X to Y" / "from X - Y"
    m = re.search(rf"from\s+{time_pat}\s*(?:to|-|–|until)\s*{time_pat}", text, re.IGNORECASE)
    if m:
        return _normalize_time(m.group(1)), _normalize_time(m.group(2)), m.group(0).strip()

    # "between X and Y"
    m = re.search(rf"between\s+{time_pat}\s*and\s*{time_pat}", text, re.IGNORECASE)
    if m:
        return _normalize_time(m.group(1)), _normalize_time(m.group(2)), m.group(0).strip()

    # "X onwards" (start only)
    m = re.search(rf"{time_pat}\s*onwards", text, re.IGNORECASE)
    if m:
        return _normalize_time(m.group(1)), None, m.group(0).strip()

    return None, None, None


def _normalize_time(t: Optional[str]) -> Optional[str]:
    """Normalize time string to 24-hour HH:MM format."""
    if not t:
        return None
    t = t.strip().upper()
    m = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM)", t)
    if m:
        h = int(m.group(1))
        mm = int(m.group(2)) if m.group(2) else 0
        ampm = m.group(3)
        if ampm == "PM" and h != 12:
            h += 12
        elif ampm == "AM" and h == 12:
            h = 0
        return f"{h:02d}:{mm:02d}"
    return t


# ---------------------------------------------------------------------------
# Impact classification
# ---------------------------------------------------------------------------

@dataclass
class ImpactFacts:
    """Structured impact facts extracted from an announcement."""

    impact_type: str = "UNKNOWN_IMPACT"
    block: Optional[str] = None
    affected_rooms: List[str] = field(default_factory=list)
    event_date: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    source_evidence: Optional[str] = None
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "impact_type": self.impact_type,
            "block": self.block,
            "affected_rooms": self.affected_rooms,
            "event_date": self.event_date,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "source_evidence": self.source_evidence,
            "confidence": self.confidence,
        }


# Indicators for each impact type (checked in priority order)
_EXEMPTION_INDICATORS = [
    r"\bexempted\b",
    r"\bexemption\b",
    r"\bBYOD\s+rooms?\s+are\s+exempted\b",
    r"\bcomputer\s+labs?\s+are\s+exempted\b",
    r"\blabs?\s+are\s+exempted\b",
    r"\brooms?\s+are\s+exempted\b",
]

_UNAVAILABLE_INDICATORS = [
    r"\brooms?\s+(?:will\s+remain\s+)?(?:closed|locked|out\s+of\s+service|unavailable)\b",
    r"\b(?:closed|locked)\s+for\s+(?:maintenance|renovation|repair)\b",
]

_BLOCK_RESTRICTION_INDICATORS = [
    r"\bentry\s+(?:is\s+)?(?:strictly\s+)?(?:prohibited|restricted|not\s+allowed)\b",
    r"\baccess\s+(?:is\s+)?(?:restricted|prohibited|denied)\b",
    r"\bbuilding\s+(?:access|entry)\s+(?:restricted|prohibited)\b",
    r"\bblock\s+\d+\s+(?:access|entry)\s+(?:restricted|prohibited|closed)\b",
]

_CANCELLATION_INDICATORS = [
    r"\bclass(?:es)?\s+(?:are\s+)?(?:cancelled|canceled|suspended)\b",
    r"\bcancellation\s+of\s+class(?:es)?\b",
    r"\bregular\s+class(?:es)?\s+(?:are\s+)?(?:suspended|cancelled)\b",
]

_VENUE_CHANGE_INDICATORS = [
    r"\b(?:shifted|relocated|moved|shifted\s+to|moved\s+to|new\s+room)\b",
    r"\bvenue\s+change\b",
    r"\bchanged\s+to\s+room\b",
    r"\bfrom\s+room\s+\S+\s+to\s+room\s+\S+\b",
]

_EVENT_LOCATION_INDICATORS = [
    r"\bvenue\s*:\s*block\b",
    r"\b(?:held|conducted|organized|scheduled)\s+(?:in|at)\s+(?:block|room)\b",
    r"\b(?:will\s+be\s+)?(?:held|conducted|organized)\s+(?:in|at)\b",
    r"\bevent\b.*\b(?:in|at)\s+(?:block|room)\b",
    r"\bresource\s+person\b",
    r"\bworkshop\b",
    r"\bseminar\b",
    r"\bguest\s+lecture\b",
    r"\bpre-placement\s+talk\b",
]


def _matches_any(text_lower: str, patterns: List[str]) -> Optional[str]:
    """Return the first matching pattern's matched text, or None."""
    for pat in patterns:
        m = re.search(pat, text_lower)
        if m:
            return m.group(0)
    return None


def classify_impact(title: str, content: str) -> ImpactFacts:
    """Classify a notice into an impact category with supporting evidence.

    This is a deterministic, priority-ordered classifier. It checks the most
    specific/actionable categories first (exemption, restriction) before
    falling back to weaker categories (event location, mention only).
    """
    combined = f"{title} {content}"
    text_lower = combined.lower()

    facts = ImpactFacts()

    # Extract rooms and blocks from the full text
    all_rooms = parse_room_list(combined)
    all_blocks = extract_block_numbers(combined)

    # Extract date and time
    event_date, date_evidence = extract_event_date(combined)
    start_time, end_time, time_evidence = extract_time_window(combined)

    # Combine evidence
    evidence_parts = []
    if date_evidence:
        evidence_parts.append(date_evidence)
    if time_evidence:
        evidence_parts.append(time_evidence)

    # --- Priority 1: ROOM_EXEMPTION ---
    exemption_match = _matches_any(text_lower, _EXEMPTION_INDICATORS)
    if exemption_match:
        facts.impact_type = "ROOM_EXEMPTION"
        facts.source_evidence = exemption_match
        facts.confidence = 0.9
        facts.affected_rooms = all_rooms
        facts.event_date = event_date
        facts.start_time = start_time
        facts.end_time = end_time
        # Block is the prefix of the first affected room, or extracted block
        if all_rooms:
            facts.block = all_rooms[0].split("-")[0]
        elif all_blocks:
            facts.block = all_blocks[0]
        # Combine exemption phrase with date/time evidence
        if evidence_parts:
            facts.source_evidence = f"{exemption_match} ({', '.join(evidence_parts)})"
        return facts

    # --- Priority 2: BLOCK_RESTRICTION ---
    restriction_match = _matches_any(text_lower, _BLOCK_RESTRICTION_INDICATORS)
    if restriction_match:
        facts.impact_type = "BLOCK_RESTRICTION"
        facts.source_evidence = restriction_match
        facts.confidence = 0.85
        facts.event_date = event_date
        if all_blocks:
            facts.block = all_blocks[0]
        elif all_rooms:
            facts.block = all_rooms[0].split("-")[0]
        if evidence_parts:
            facts.source_evidence = f"{restriction_match} ({', '.join(evidence_parts)})"
        return facts

    # --- Priority 3: CLASS_CANCELLATION ---
    cancellation_match = _matches_any(text_lower, _CANCELLATION_INDICATORS)
    if cancellation_match:
        facts.impact_type = "CLASS_CANCELLATION"
        facts.source_evidence = cancellation_match
        facts.confidence = 0.8
        facts.affected_rooms = all_rooms
        facts.event_date = event_date
        facts.start_time = start_time
        facts.end_time = end_time
        if all_rooms:
            facts.block = all_rooms[0].split("-")[0]
        elif all_blocks:
            facts.block = all_blocks[0]
        if evidence_parts:
            facts.source_evidence = f"{cancellation_match} ({', '.join(evidence_parts)})"
        return facts

    # --- Priority 4: ROOM_UNAVAILABLE ---
    unavailable_match = _matches_any(text_lower, _UNAVAILABLE_INDICATORS)
    if unavailable_match:
        facts.impact_type = "ROOM_UNAVAILABLE"
        facts.source_evidence = unavailable_match
        facts.confidence = 0.8
        facts.affected_rooms = all_rooms
        facts.event_date = event_date
        facts.start_time = start_time
        facts.end_time = end_time
        if all_rooms:
            facts.block = all_rooms[0].split("-")[0]
        elif all_blocks:
            facts.block = all_blocks[0]
        if evidence_parts:
            facts.source_evidence = f"{unavailable_match} ({', '.join(evidence_parts)})"
        return facts

    # --- Priority 5: VENUE_CHANGE ---
    venue_match = _matches_any(text_lower, _VENUE_CHANGE_INDICATORS)
    if venue_match:
        facts.impact_type = "VENUE_CHANGE"
        facts.source_evidence = venue_match
        facts.confidence = 0.75
        facts.affected_rooms = all_rooms
        facts.event_date = event_date
        if all_rooms:
            facts.block = all_rooms[0].split("-")[0]
        elif all_blocks:
            facts.block = all_blocks[0]
        if evidence_parts:
            facts.source_evidence = f"{venue_match} ({', '.join(evidence_parts)})"
        return facts

    # --- Priority 6: EVENT_LOCATION ---
    # Only classify as event location if rooms/blocks are mentioned AND
    # an event indicator is present, but NO exemption/restriction/cancellation.
    event_match = _matches_any(text_lower, _EVENT_LOCATION_INDICATORS)
    if event_match and (all_rooms or all_blocks):
        facts.impact_type = "EVENT_LOCATION"
        facts.source_evidence = event_match
        facts.confidence = 0.65
        facts.affected_rooms = all_rooms
        facts.event_date = event_date
        facts.start_time = start_time
        if all_rooms:
            facts.block = all_rooms[0].split("-")[0]
        elif all_blocks:
            facts.block = all_blocks[0]
        return facts

    # --- Priority 7: ROOM_MENTION_ONLY ---
    # Rooms or blocks are mentioned but no impact indicator matches.
    if all_rooms or all_blocks:
        facts.impact_type = "ROOM_MENTION_ONLY"
        facts.affected_rooms = all_rooms
        facts.confidence = 0.4
        if all_rooms:
            facts.block = all_rooms[0].split("-")[0]
        elif all_blocks:
            facts.block = all_blocks[0]
        # Find the sentence containing the first room/block mention
        first_mention = all_rooms[0] if all_rooms else f"Block {all_blocks[0]}"
        sentence = _find_sentence_containing(combined, first_mention)
        facts.source_evidence = sentence[:200] if sentence else first_mention
        return facts

    # --- Fallback: UNKNOWN_IMPACT ---
    facts.impact_type = "UNKNOWN_IMPACT"
    facts.confidence = 0.1
    return facts


def _find_sentence_containing(text: str, needle: str) -> Optional[str]:
    """Return the sentence containing the first occurrence of needle."""
    idx = text.lower().find(needle.lower())
    if idx < 0:
        return None
    # Find sentence boundaries
    start = max(text.rfind(". ", 0, idx), text.rfind("\n", 0, idx), 0)
    end = min(
        text.find(". ", idx),
        text.find("\n", idx),
        text.find("! ", idx),
        text.find("? ", idx),
        len(text),
    )
    if end == -1:
        end = len(text)
    return text[start:end].strip()


def is_location_impact_query(query: str) -> bool:
    """Detect whether a user query is asking about location/room impact.

    Returns True for queries like:
      - "What announcements affect Block 34?"
      - "Which rooms in Block 34 are exempted?"
      - "Are any rooms unavailable in Block 27?"
    Returns False for general queries like "What is the exam schedule?"
    """
    if not query:
        return False
    q_lower = query.lower()
    impact_keywords = [
        "affect", "affects", "affected", "impact", "impacted",
        "exempt", "exempted", "exemption",
        "unavailable", "closed", "restricted", "prohibited",
        "cancelled", "canceled", "suspended",
        "relocated", "shifted", "venue change",
        "which rooms", "what rooms", "rooms in",
    ]
    location_keywords = ["block", "building", "room", "lab", "byod"]

    has_impact = any(kw in q_lower for kw in impact_keywords)
    has_location = any(kw in q_lower for kw in location_keywords)

    return has_impact and has_location


def extract_query_block(query: str) -> Optional[str]:
    """Extract the block number from a location-impact query.

    e.g. "What announcements affect Block 34?" → "34"
    """
    if not query:
        return None
    m = re.search(r"(?:block|building)\s*(\d{1,2})\b", query, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def extract_query_impact_type(query: str) -> Optional[str]:
    """Extract the specific impact type requested in the query.

    Returns one of: ROOM_EXEMPTION, ROOM_UNAVAILABLE, BLOCK_RESTRICTION,
    CLASS_CANCELLATION, VENUE_CHANGE, EVENT_LOCATION, or None (general).
    """
    if not query:
        return None
    q_lower = query.lower()

    if any(w in q_lower for w in ["exempt", "exemption", "exempted"]):
        return "ROOM_EXEMPTION"
    if any(w in q_lower for w in ["unavailable", "closed", "out of service"]):
        return "ROOM_UNAVAILABLE"
    if any(w in q_lower for w in ["restrict", "prohibit", "entry", "access"]):
        return "BLOCK_RESTRICTION"
    if any(w in q_lower for w in ["cancel", "canceled", "cancelled", "suspended"]):
        return "CLASS_CANCELLATION"
    if any(w in q_lower for w in ["relocat", "shift", "venue change", "moved"]):
        return "VENUE_CHANGE"
    if any(w in q_lower for w in ["event", "held", "conducted", "workshop", "seminar"]):
        return "EVENT_LOCATION"
    return None
