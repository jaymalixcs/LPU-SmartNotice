import re
from typing import List

def normalize_room_string(room_str: str) -> List[str]:
    if not room_str:
        return []
    
    results = []
    # 1. Find patterns like 34-105 or 34-304X
    pattern_dash = r"\b(\d{1,2})-(\d{3}[A-Za-z]?)\b"
    for block, room in re.findall(pattern_dash, room_str):
        results.append(f"{block}-{room.upper()}")

    # 2. Find pattern like Block 34 Room 105
    pattern_block_room = r"block\s*(\d{1,2})[^\d]*room\s*(\d{3}[A-Za-z]?)"
    for block, room in re.findall(pattern_block_room, room_str.lower()):
        results.append(f"{block}-{room.upper()}")

    # 3. Find 5-digit LPU notation e.g. 34304X, 14106, 26304Y, 55303
    pattern_lpu = r"\b(\d{2})(\d{3}[A-Za-z]?)\b"
    for block, room in re.findall(pattern_lpu, room_str):
        r_str = f"{block}-{room.upper()}"
        if r_str not in results:
            results.append(r_str)

    if results:
        # Deduplicate while preserving order
        return list(dict.fromkeys(results))
    return [room_str.strip()]

exam_notice = "SUSPENSION OF CLASSES. Block 34: Rooms 34304X, 34306 are suspended on 28-10-2026. Rooms 34-101 and 34-102 are explicitly EXEMPTED."
print("All normalized rooms in exam_notice:", normalize_room_string(exam_notice))

