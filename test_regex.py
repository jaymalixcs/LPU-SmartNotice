import re

exam_notice = "SUSPENSION OF CLASSES. Block 34: Rooms 34304X, 34306 are suspended on 28-10-2026. Rooms 34-101 and 34-102 are explicitly EXEMPTED."
pattern_lpu = r"\b(\d{2})(\d{3}[A-Za-z]?)\b"
print("LPU regex matches in exam_notice:", re.findall(pattern_lpu, exam_notice))

# Check exemption patterns
pat_after = r"(\d{1,2}-\d{3}[A-Za-z]?)\s*(?:and\s*(\d{1,2}-\d{3}[A-Za-z]?))?\s*(?:are|is)?\s*(?:explicitly\s*)?(?:exempted|exempt)"
print("After regex matches:", re.findall(pat_after, exam_notice.lower()))

