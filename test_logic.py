import re
from typing import List, Optional
from app.models.student import TimetableEntry, ClassImpactResult
from app.models.announcement import RawAnnouncement

def normalize_room_string(room_str: str) -> List[str]:
    if not room_str:
        return []
    pattern_dash = r"\b(\d{1,2})-(\d{3}[A-Za-z]?)\b"
    matches = re.findall(pattern_dash, room_str)
    if matches:
        return [f"{block}-{room.upper()}" for block, room in matches]
    pattern_block_room = r"block\s*(\d{1,2})[^\d]*room\s*(\d{3}[A-Za-z]?)"
    matches_br = re.findall(pattern_block_room, room_str.lower())
    if matches_br:
        return [f"{block}-{room.upper()}" for block, room in matches_br]
    pattern_lpu = r"\b(\d{2})(\d{3}[A-Za-z]?)\b"
    matches_lpu = re.findall(pattern_lpu, room_str)
    if matches_lpu:
        return [f"{block}-{room.upper()}" for block, room in matches_lpu]
    return [room_str.strip()]

def room_matches(r1: str, r2: str) -> bool:
    if not r1 or not r2:
        return False
    clean1 = r1.replace("-", "").replace(" ", "").upper()
    clean2 = r2.replace("-", "").replace(" ", "").upper()
    return clean1 == clean2

# Test MindMatrix vs 34-303
mindmatrix_text = """New MindMatrix: A Competition of Speed and Strategy ( LPU/20.2/ST/2024/001/IC/261027/0002 ) Oct 27,2026
Venue: Block 34-411
Date: 27th October, 2026
Time: 04:00 PM Onwards"""

affected = normalize_room_string(mindmatrix_text)
print("MindMatrix affected rooms detected:", affected)
print("Does 34-303 match 34-411?", room_matches("34-303", "34-411"))

