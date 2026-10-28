import re
from typing import List

def normalize_room_string(room_str: str) -> List[str]:
    if not room_str:
        return []
    results = []
    pattern_dash = r"\b(\d{1,2})-(\d{3}[A-Za-z]?)\b"
    for block, room in re.findall(pattern_dash, room_str):
        results.append(f"{block}-{room.upper()}")

    pattern_block_room = r"block\s*(\d{1,2})[^\d]*room\s*(\d{3}[A-Za-z]?)"
    for block, room in re.findall(pattern_block_room, room_str.lower()):
        results.append(f"{block}-{room.upper()}")

    pattern_lpu = r"\b(\d{2})(\d{3}[A-Za-z]?)\b"
    for block, room in re.findall(pattern_lpu, room_str):
        r_str = f"{block}-{room.upper()}"
        if r_str not in results:
            results.append(r_str)

    if results:
        return list(dict.fromkeys(results))
    return [room_str.strip()]

def room_matches(r1: str, r2: str) -> bool:
    if not r1 or not r2:
        return False
    clean1 = r1.replace("-", "").replace(" ", "").upper()
    clean2 = r2.replace("-", "").replace(" ", "").upper()
    return clean1 == clean2

def check_test(room_to_test, ann_title, ann_content, att=False):
    ann_text = f"{ann_title} {ann_content}".lower()
    affected_rooms = normalize_room_string(ann_text)
    entry_rooms = normalize_room_string(room_to_test)
    entry_room_clean = entry_rooms[0] if entry_rooms else room_to_test.strip()
    
    entry_block = ""
    block_match = re.search(r"(\d{1,2})", entry_room_clean)
    if block_match:
        entry_block = block_match.group(1)

    exempted_rooms = []
    # Both: "exempted: room 34-101" and "room 34-101 is exempted"
    except_patterns = [
        r"(?:except|excluding|exempted|exemption for)\s*(?:room|rooms)?\s*(\d{1,2}-\d{3}[A-Za-z]?)",
        r"(?:except|excluding|exempted)\s*(?:in|for)?\s*(?:block\s*\d{1,2}\s*)?(?:room\s*)?(\d{1,2}-\d{3}[A-Za-z]?)",
        r"(\d{1,2}-\d{3}[A-Za-z]?)\s*(?:and\s*(\d{1,2}-\d{3}[A-Za-z]?))?\s*(?:are|is)?\s*(?:explicitly\s*)?(?:exempted|exempt)"
    ]
    for pat in except_patterns:
        for m in re.findall(pat, ann_text):
            if isinstance(m, tuple):
                for item in m:
                    if item:
                        exempted_rooms.extend(normalize_room_string(item))
            else:
                exempted_rooms.extend(normalize_room_string(m))

    impact_words = ["cancelled", "canceled", "suspended", "postponed", "relocated", "moved", "exam", "holiday"]
    has_impact_word = any(w in ann_text for w in impact_words)

    att_phrases = ["refer attachment", "refer to attached", "attached list", "attached herewith", "see attachment", "attachment for rooms", "attached pdf"]
    is_attachment_dependent = bool(att and any(p in ann_text for p in att_phrases))

    # 1. Exemptions
    if any(room_matches(ex, entry_room_clean) for ex in exempted_rooms):
        return "EXEMPTED", False

    # 2. Room match
    room_match = any(room_matches(r, entry_room_clean) for r in affected_rooms if not any(room_matches(r, ex) for ex in exempted_rooms))

    building_wide_phrases = [
        "all rooms in block", "entire building", "whole building", "entire block",
        "whole block", "all classes in block", "restricted movement area",
        "building closed", "closure of block", "block suspended", "evacuation"
    ]
    is_building_wide = any(phrase in ann_text for phrase in building_wide_phrases)

    block_match_flag = False
    if entry_block and (f"block {entry_block}" in ann_text or f"block-{entry_block}" in ann_text or f"building {entry_block}" in ann_text or f"building: {entry_block}" in ann_text):
        if is_building_wide:
            block_match_flag = True
        elif is_attachment_dependent and not affected_rooms:
            block_match_flag = True
        elif not affected_rooms and has_impact_word:
            block_match_flag = True

    if not room_match and not block_match_flag:
        return "NO_MATCH", False

    if block_match_flag and not room_match and is_attachment_dependent:
        return "ATTACHMENT_DEPENDENT", True

    if room_match:
        if has_impact_word:
            return "CONFIRMED_MATCH", True
        else:
            return "POTENTIAL_IMPACT", True

    if block_match_flag:
        return "POTENTIAL_IMPACT", True

    return "NO_MATCH", False

# Test 1: MindMatrix vs 34-303
status1, aff1 = check_test("34-303", "MindMatrix: A Competition of Speed and Strategy", "Venue: Block 34-411 on 27 October 2026")
print("Test 1 (MindMatrix vs 34-303):", status1, "Affected:", aff1)

# Test 2: Exam Notice vs 34-304X (Suspended)
exam_notice = "SUSPENSION OF CLASSES FOR EXAM. Block 34: Rooms 34304X, 34306 are suspended on 28-10-2026. Rooms 34-101 and 34-102 are explicitly EXEMPTED."
status2, aff2 = check_test("34-304X", "Exam Suspension", exam_notice)
print("Test 2 (Exam Notice vs 34-304X):", status2, "Affected:", aff2)

# Test 3: Exam Notice vs 34-101 (Exempted)
status3, aff3 = check_test("34-101", "Exam Suspension", exam_notice)
print("Test 3 (Exam Notice vs 34-101):", status3, "Affected:", aff3)

# Test 4: Exam Notice vs 34-303 (Normal class, not in list)
status4, aff4 = check_test("34-303", "Exam Suspension", exam_notice)
print("Test 4 (Exam Notice vs 34-303):", status4, "Affected:", aff4)

