import re

ann_text = """suspension of classes for conduct of external agency examination
1. building 34 (block 34):
- rooms 34304x, 34306, 34306x: suspended for the entire day on 27th & 28th october 2026.
- rooms 34-101 and 34-102: explicitly exempted from suspension (classes in 34-101 and 34-102 will be conducted normally).
2. building 32:
- examination seating allocated across upper levels. please refer attachment for complete list of secondary room relocations."""

except_patterns = [
    r"(?:except|excluding|exempted|exemption for)\s*(?:room|rooms)?\s*(\d{1,2}-\d{3}[A-Za-z]?)",
    r"(?:except|excluding|exempted)\s*(?:in|for)?\s*(?:block\s*\d{1,2}\s*)?(?:room\s*)?(\d{1,2}-\d{3}[A-Za-z]?)",
    r"(\d{1,2}-\d{3}[A-Za-z]?)\s*(?:and\s*(\d{1,2}-\d{3}[A-Za-z]?))?\s*(?:are|is)?\s*(?:explicitly\s*)?(?:exempted|exempt)",
    r"exempt(?:ions?)?[:\s-]+(?:rooms?\s*)?(\d{1,2}-\d{3}[A-Za-z]?)(?:\s*and\s*(\d{1,2}-\d{3}[A-Za-z]?))?"
]

for pat in except_patterns:
    print("Pattern:", pat)
    print("  Matches:", re.findall(pat, ann_text))

