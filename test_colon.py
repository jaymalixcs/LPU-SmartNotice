import re

ann_text = "- rooms 34-101 and 34-102: explicitly exempted from suspension"

pat = r"(\d{1,2}-\d{3}[A-Za-z]?)\s*(?:and\s*(\d{1,2}-\d{3}[A-Za-z]?))?[:\s]*(?:are|is)?\s*(?:explicitly\s*)?(?:exempted|exempt)"
print("Matches with [:\\s]*:", re.findall(pat, ann_text))

