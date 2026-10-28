import re
from typing import List, Dict, Any, Optional, Tuple
from app.models.student import TimetableEntry, ClassImpactResult
from app.models.announcement import RawAnnouncement, ExtractedAnnouncementMetadata
from app.core.logging_config import logger

class RoomImpactService:
    """Analyzes room numbers, ranges, and timetable overlap for student class impact."""

    def normalize_room_string(self, room_str: str) -> List[str]:
        """Extract standard block-room strings e.g. '34-105' from various input formats."""
        if not room_str:
            return []

        results: List[str] = []

        # Find patterns like 34-105 or 34-304X
        pattern_dash = r"\b(\d{1,2})-(\d{3}[A-Za-z]?)\b"
        for block, room in re.findall(pattern_dash, room_str):
            results.append(f"{block}-{room.upper()}")

        # Find pattern like Block 34 Room 105
        pattern_block_room = r"block\s*(\d{1,2})[^\d]*room\s*(\d{3}[A-Za-z]?)"
        for block, room in re.findall(pattern_block_room, room_str.lower()):
            results.append(f"{block}-{room.upper()}")

        # Find 5-digit LPU notation e.g. 34304X, 14106, 26304Y, 55303
        pattern_lpu = r"\b(\d{2})(\d{3}[A-Za-z]?)\b"
        for block, room in re.findall(pattern_lpu, room_str):
            r_str = f"{block}-{room.upper()}"
            if r_str not in results:
                results.append(r_str)

        if results:
            return list(dict.fromkeys(results))

        return [room_str.strip()]

    def parse_room_range(self, range_str: str) -> List[str]:
        """Expand room ranges like '34-101 to 34-105' into ['34-101', '34-102', '34-103', '34-104', '34-105']."""
        if not range_str:
            return []

        range_pattern = r"(\d{1,2})-(\d{3})\s*(?:to|-|through)\s*(\d{1,2})-(\d{3})"
        match = re.search(range_pattern, range_str.lower())
        if match:
            b1, r1, b2, r2 = match.groups()
            if b1 == b2:
                try:
                    start_num = int(r1)
                    end_num = int(r2)
                    if start_num <= end_num and (end_num - start_num) <= 50:
                        return [f"{b1}-{num:03d}" for num in range(start_num, end_num + 1)]
                except ValueError:
                    pass

        return self.normalize_room_string(range_str)

    def check_timetable_conflict(
        self,
        entry: TimetableEntry,
        announcement: RawAnnouncement,
        metadata: Optional[ExtractedAnnouncementMetadata] = None
    ) -> ClassImpactResult:
        """Check if an announcement impacts a specific timetable entry."""
        ann_text = f"{announcement.title} {announcement.full_content}".lower()

        # Extract affected rooms from metadata or text regex
        affected_rooms: List[str] = []
        if metadata:
            affected_rooms.extend(metadata.affected_rooms)
            if metadata.room:
                affected_rooms.extend(self.normalize_room_string(metadata.room))
            if metadata.room_range:
                affected_rooms.extend(self.parse_room_range(metadata.room_range))
            if metadata.location:
                affected_rooms.extend(self.normalize_room_string(metadata.location))

        if not affected_rooms:
            # Fallback to regex over announcement text
            affected_rooms = self.normalize_room_string(ann_text)
            if "range" in ann_text or "to" in ann_text:
                affected_rooms.extend(self.parse_room_range(ann_text))

        entry_rooms = self.normalize_room_string(entry.room)
        entry_room_clean = entry_rooms[0] if entry_rooms else entry.room.strip()

        # Extract building/block
        entry_block = ""
        block_match = re.search(r"(\d{1,2})", entry_room_clean)
        if block_match:
            entry_block = block_match.group(1)

        # 1. Check Explicit Room Exemptions
        exempted_rooms: List[str] = []

        # Check regex exception phrases directly in announcement text (both prefix and suffix forms)
        except_patterns = [
            r"(?:except|excluding|exempted|exemption for|exemptions?)\s*[:\s-]*(?:rooms?)?\s*(\d{1,2}-\d{3}[A-Za-z]?)",
            r"(?:except|excluding|exempted)\s*(?:in|for)?\s*(?:block\s*\d{1,2}\s*)?(?:room\s*)?(\d{1,2}-\d{3}[A-Za-z]?)",
            r"(\d{1,2}-\d{3}[A-Za-z]?)\s*(?:and\s*(\d{1,2}-\d{3}[A-Za-z]?))?[:\s]*(?:are|is)?\s*(?:explicitly\s*)?(?:exempted|exempt)"
        ]
        for pat in except_patterns:
            matches_ex = re.findall(pat, ann_text)
            for m in matches_ex:
                if isinstance(m, tuple):
                    for item in m:
                        if item:
                            exempted_rooms.extend(self.normalize_room_string(item))
                else:
                    exempted_rooms.extend(self.normalize_room_string(m))

        # Determine impact type
        impact_type = "GENERAL_ALERT"
        if any(w in ann_text for w in ["cancelled", "canceled", "suspended", "holiday", "closed", "non-teaching", "suspension"]):
            impact_type = "SUSPENSION"
        elif any(w in ann_text for w in ["relocated", "shifted", "venue change", "moved to", "new room", "venue shift"]):
            impact_type = "VENUE_CHANGE"
        elif any(w in ann_text for w in ["exam", "examination", "viva", "seating plan", "mid-term", "end-term"]):
            impact_type = "EXAM_DUTY"
        elif any(w in ann_text for w in ["rescheduled", "postponed", "timing changed"]):
            impact_type = "RESCHEDULED"

        # Check for attachment-dependent room instructions
        att_phrases = ["refer attachment", "refer to attached", "attached list", "attached herewith", "see attachment", "attachment for rooms", "attached pdf"]
        is_attachment_dependent = bool(announcement.attachment_present and any(p in ann_text for p in att_phrases))

        def room_matches(r1: str, r2: str) -> bool:
            if not r1 or not r2:
                return False
            clean1 = r1.replace("-", "").replace(" ", "").upper()
            clean2 = r2.replace("-", "").replace(" ", "").upper()
            return clean1 == clean2

        if any(room_matches(ex, entry_room_clean) for ex in exempted_rooms):
            return ClassImpactResult(
                entry=entry,
                affected=False,
                status="EXEMPTED",
                impact_type="NONE",
                announcement_id=announcement.announcement_id,
                announcement_title=announcement.title,
                evidence_text=f"Explicit exemption found matching {entry.room}",
                explanation=f"Exempted: Room {entry.room} ({entry.course_code}) is explicitly exempted from this announcement."
            )

        # 2. Exact Room Match Check
        room_match = False
        for room in affected_rooms:
            if not any(room_matches(room, ex) for ex in exempted_rooms):
                if room_matches(room, entry_room_clean):
                    room_match = True
                    break

        # 3. Block/Building Level Match
        # Only true building-wide impact if whole-block closure is specified, or attachment-dependent without specific room lists
        building_wide_phrases = [
            "all rooms in block", "entire building", "whole building", "entire block",
            "whole block", "all classes in block", "restricted movement area",
            "building closed", "closure of block", "block suspended", "evacuation",
            "all laboratories in block", "classes stand suspended in block"
        ]
        is_building_wide = any(phrase in ann_text for phrase in building_wide_phrases)

        impact_words = ["cancelled", "canceled", "suspended", "postponed", "relocated", "moved", "exam", "holiday"]
        has_impact_word = any(w in ann_text for w in impact_words)

        block_match_flag = False
        if entry_block and (f"block {entry_block}" in ann_text or f"block-{entry_block}" in ann_text or f"building {entry_block}" in ann_text or f"building: {entry_block}" in ann_text or f"building  {entry_block}" in ann_text):
            has_specific_rooms_in_this_block = any(r.startswith(f"{entry_block}-") for r in affected_rooms)
            if is_building_wide:
                block_match_flag = True
            elif is_attachment_dependent and not has_specific_rooms_in_this_block:
                block_match_flag = True
            elif not has_specific_rooms_in_this_block and has_impact_word:
                block_match_flag = True

        if not room_match and not block_match_flag:
            return ClassImpactResult(
                entry=entry,
                affected=False,
                status="NO_MATCH",
                impact_type="NONE",
                explanation=f"No room overlap detected for class in {entry.room}."
            )

        # If block matches and notice states room details are in attachment
        if block_match_flag and not room_match and is_attachment_dependent:
            return ClassImpactResult(
                entry=entry,
                affected=True,
                status="ATTACHMENT_DEPENDENT",
                impact_type=impact_type,
                announcement_id=announcement.announcement_id,
                announcement_title=announcement.title,
                evidence_text="Notice references attachment for detailed room schedule",
                explanation=f"Attachment Dependent: Announcement affects Block {entry_block}, but individual room schedules are specified in an attachment whose content is unretrieved. Please verify official attachment file."
            )

        if room_match:
            if has_impact_word:
                return ClassImpactResult(
                    entry=entry,
                    affected=True,
                    status="CONFIRMED_MATCH",
                    impact_type=impact_type,
                    announcement_id=announcement.announcement_id,
                    announcement_title=announcement.title,
                    evidence_text=f"Direct room match: {entry.room} with {impact_type} impact",
                    explanation=f"Confirmed match: Announcement affects Room {entry.room} ({entry.course_code}) [{impact_type}]."
                )
            else:
                return ClassImpactResult(
                    entry=entry,
                    affected=True,
                    status="POTENTIAL_IMPACT",
                    impact_type=impact_type,
                    announcement_id=announcement.announcement_id,
                    announcement_title=announcement.title,
                    evidence_text=f"Notice references Room {entry.room}",
                    explanation=f"Potential impact: Announcement references Room {entry.room}, but specific class cancellation is unconfirmed."
                )

        if block_match_flag:
            return ClassImpactResult(
                entry=entry,
                affected=True,
                status="POTENTIAL_IMPACT",
                impact_type=impact_type,
                announcement_id=announcement.announcement_id,
                announcement_title=announcement.title,
                evidence_text=f"Notice affects Block {entry_block}",
                explanation=f"Building impact: Announcement affects Block {entry_block} where your class {entry.course_code} ({entry.room}) is held."
            )

        return ClassImpactResult(
            entry=entry,
            affected=False,
            status="UNCERTAIN_DATA",
            impact_type="NONE",
            explanation="Insufficient room or date details in announcement to determine class impact."
        )

    def get_sample_timetable(self, student_id: str) -> List[TimetableEntry]:
        """Fetch student's registered timetable from SQLite DB or return default demo classes."""
        try:
            from app.core.database import get_db_connection
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM student_timetables WHERE student_id = ? ORDER BY day_or_date, start_time", (student_id,))
            rows = cursor.fetchall()
            conn.close()
            if rows:
                entries = []
                for r in rows:
                    raw_room = r["room"] or ""
                    building = r["building"]
                    if not building:
                        norm = self.normalize_room_string(raw_room)
                        b_num = norm[0].split("-")[0] if norm and "-" in norm[0] else ""
                        building = f"Block {b_num}" if b_num else "Campus"

                    entries.append(
                        TimetableEntry(
                            entry_id=r["entry_id"],
                            student_id=r["student_id"],
                            day_or_date=r["day_or_date"],
                            start_time=r["start_time"],
                            end_time=r["end_time"],
                            course_code=r["course_code"],
                            course_name=r["course_name"],
                            room=raw_room,
                            building=building,
                            faculty=r["faculty"]
                        )
                    )
                return entries
        except Exception as exc:
            logger.warning("Error loading timetable from DB for %s: %s", student_id, exc)

        return [
            TimetableEntry(
                entry_id="TT-101",
                student_id=student_id,
                day_or_date="2026-10-28",
                start_time="09:00 AM",
                end_time="10:00 AM",
                course_code="CSE301",
                course_name="Data Structures & Algorithms",
                room="34-105",
                building="Block 34",
                faculty="Dr. Sharma"
            ),
            TimetableEntry(
                entry_id="TT-102",
                student_id=student_id,
                day_or_date="2026-10-28",
                start_time="10:00 AM",
                end_time="11:00 AM",
                course_code="INT219",
                course_name="Front End Web Development",
                room="34-101",
                building="Block 34",
                faculty="Prof. Gupta"
            ),
            TimetableEntry(
                entry_id="TT-103",
                student_id=student_id,
                day_or_date="2026-10-28",
                start_time="11:00 AM",
                end_time="12:00 PM",
                course_code="CSE316",
                course_name="Operating Systems",
                room="34-304X",
                building="Block 34",
                faculty="Dr. Singh"
            ),
            TimetableEntry(
                entry_id="TT-104",
                student_id=student_id,
                day_or_date="2026-10-28",
                start_time="02:00 PM",
                end_time="03:00 PM",
                course_code="MTH202",
                course_name="Discrete Mathematics",
                room="32-201",
                building="Block 32",
                faculty="Prof. Verma"
            )
        ]
