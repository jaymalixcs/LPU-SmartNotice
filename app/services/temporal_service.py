import re
from datetime import datetime, timedelta
from typing import List, Set, Optional, Dict, Any

MONTH_NAME_TO_NUM = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12
}

def resolve_target_dates(query: str, ref_date: Optional[datetime] = None) -> List[str]:
    """
    Resolve temporal intent in user query to concrete ISO dates (YYYY-MM-DD).
    Supports: today, tomorrow, yesterday, explicit dates (27th Oct, 28-10-2026, October 27),
    and relative weekday references.
    """
    if ref_date is None:
        ref_date = datetime.now()

    q = query.lower()
    targets: Set[str] = set()

    # Relative temporal words
    if re.search(r"\btoday\b|\btonight\b|\bthis day\b", q):
        targets.add(ref_date.strftime("%Y-%m-%d"))

    if re.search(r"\btomorrow\b|\bnext day\b", q):
        targets.add((ref_date + timedelta(days=1)).strftime("%Y-%m-%d"))

    if re.search(r"\byesterday\b", q):
        targets.add((ref_date - timedelta(days=1)).strftime("%Y-%m-%d"))

    # Weekday patterns: "this monday", "on tuesday", etc.
    weekdays = {
        "monday": 0, "tuesday": 1, "wednesday": 2,
        "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6
    }
    for day_name, day_idx in weekdays.items():
        if re.search(rf"\b(this|on|coming)\s+{day_name}\b|\b{day_name}\b", q):
            # If student specifically mentions a weekday, calculate date in current week
            current_day_idx = ref_date.weekday()
            diff = day_idx - current_day_idx
            target_dt = ref_date + timedelta(days=diff)
            targets.add(target_dt.strftime("%Y-%m-%d"))

    # Explicit date formats:
    # 1. "27th & 28th October 2026" or "27 and 28 Oct"
    range_match = re.findall(
        r"(\d{1,2})(?:st|nd|rd|th)?\s*(?:&|and|,|-|to)\s*(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)\s*(\d{4})?",
        q
    )
    for d1, d2, m_str, y_str in range_match:
        m_prefix = m_str[:3]
        if m_prefix in MONTH_NAME_TO_NUM:
            y = int(y_str) if y_str else ref_date.year
            m_num = MONTH_NAME_TO_NUM[m_prefix]
            try:
                targets.add(f"{y:04d}-{m_num:02d}-{int(d1):02d}")
                targets.add(f"{y:04d}-{m_num:02d}-{int(d2):02d}")
            except ValueError:
                pass

    # 2. "27th October 2026", "27 Oct", "October 27"
    single_match = re.findall(
        r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)\s*(\d{4})?",
        q
    )
    for d_str, m_str, y_str in single_match:
        m_prefix = m_str[:3]
        if m_prefix in MONTH_NAME_TO_NUM:
            y = int(y_str) if y_str else ref_date.year
            m_num = MONTH_NAME_TO_NUM[m_prefix]
            try:
                targets.add(f"{y:04d}-{m_num:02d}-{int(d_str):02d}")
            except ValueError:
                pass

    month_first_match = re.findall(
        r"\b([a-z]+)\s+([0-2]?[1-9]|10|20|30|31)(?:st|nd|rd|th)?(?:\s*,?\s*(\d{4}))?\b",
        q
    )
    for m_str, d_str, y_str in month_first_match:
        m_prefix = m_str[:3]
        if m_prefix in MONTH_NAME_TO_NUM:
            y = int(y_str) if y_str else ref_date.year
            m_num = MONTH_NAME_TO_NUM[m_prefix]
            try:
                targets.add(f"{y:04d}-{m_num:02d}-{int(d_str):02d}")
            except ValueError:
                pass

    # 3. Numeric ISO formats: "2026-10-27" or "27-10-2026" or "27/10/2026"
    iso_matches = re.findall(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", q)
    for y, m, d in iso_matches:
        targets.add(f"{int(y):04d}-{int(m):02d}-{int(d):02d}")

    dmy_matches = re.findall(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b", q)
    for d, m, y in dmy_matches:
        targets.add(f"{int(y):04d}-{int(m):02d}-{int(d):02d}")

    return sorted(list(targets))


def extract_notice_dates(pub_date: str, content: str, title: str = "") -> List[str]:
    """
    Extract all concrete ISO calendar dates (YYYY-MM-DD) that an announcement
    explicitly references, governs, or was published on.
    """
    dates_found: Set[str] = set()
    combined_text = f"{title} {content}".lower()

    # Normalize publication date (e.g. "2026-10-27" or "9/17/2026")
    if pub_date:
        pub_clean = pub_date.strip()
        m_iso = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", pub_clean)
        if m_iso:
            y, m, d = m_iso.groups()
            dates_found.add(f"{int(y):04d}-{int(m):02d}-{int(d):02d}")
        else:
            m_slash = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})", pub_clean)
            if m_slash:
                # Could be M/D/YYYY or D/M/YYYY
                p1, p2, py = m_slash.groups()
                # Guess default LPU dataset format M/D/YYYY
                dates_found.add(f"{int(py):04d}-{int(p1):02d}-{int(p2):02d}")

    # Extract date ranges in text e.g. "27th & 28th October 2026"
    range_matches = re.findall(
        r"(\d{1,2})(?:st|nd|rd|th)?\s*(?:&|and|,|-|to)\s*(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)\s*(\d{4})?",
        combined_text
    )
    for d1, d2, m_str, y_str in range_matches:
        m_prefix = m_str[:3]
        if m_prefix in MONTH_NAME_TO_NUM:
            y = int(y_str) if y_str else 2026
            m_num = MONTH_NAME_TO_NUM[m_prefix]
            try:
                dates_found.add(f"{y:04d}-{m_num:02d}-{int(d1):02d}")
                dates_found.add(f"{y:04d}-{m_num:02d}-{int(d2):02d}")
            except ValueError:
                pass

    # Extract single dates in text e.g. "27th October 2026" or "26 October 2026"
    single_matches = re.findall(
        r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)\s*(\d{4})?",
        combined_text
    )
    for d_str, m_str, y_str in single_matches:
        m_prefix = m_str[:3]
        if m_prefix in MONTH_NAME_TO_NUM:
            y = int(y_str) if y_str else 2026
            m_num = MONTH_NAME_TO_NUM[m_prefix]
            try:
                dates_found.add(f"{y:04d}-{m_num:02d}-{int(d_str):02d}")
            except ValueError:
                pass

    # Standard numeric dates in text
    iso_in_text = re.findall(r"\b(\d{4})-(\d{2})-(\d{2})\b", combined_text)
    for y, m, d in iso_in_text:
        dates_found.add(f"{y}-{m}-{d}")

    return sorted(list(dates_found))


def is_notice_applicable_to_date(pub_date: str, content: str, target_date_iso: str, title: str = "") -> bool:
    """Check if an announcement covers or applies to the requested target date."""
    notice_dates = extract_notice_dates(pub_date, content, title)
    return target_date_iso in notice_dates


def build_temporal_prompt_context(query: str, ref_date: Optional[datetime] = None) -> Dict[str, Any]:
    """Build structured temporal instruction and context for Gemini prompt grounding."""
    if ref_date is None:
        ref_date = datetime.now()

    today_iso = ref_date.strftime("%Y-%m-%d")
    today_name = ref_date.strftime("%A")
    today_human = ref_date.strftime("%d %B %Y")

    tomorrow_dt = ref_date + timedelta(days=1)
    tomorrow_iso = tomorrow_dt.strftime("%Y-%m-%d")
    tomorrow_name = tomorrow_dt.strftime("%A")
    tomorrow_human = tomorrow_dt.strftime("%d %B %Y")

    yesterday_dt = ref_date - timedelta(days=1)
    yesterday_iso = yesterday_dt.strftime("%Y-%m-%d")
    yesterday_name = yesterday_dt.strftime("%A")
    yesterday_human = yesterday_dt.strftime("%d %B %Y")

    targets = resolve_target_dates(query, ref_date)

    if targets:
        target_descs = []
        for t in targets:
            if t == today_iso:
                target_descs.append(f"TODAY ({today_name}, {today_human} — ISO: {today_iso})")
            elif t == tomorrow_iso:
                target_descs.append(f"TOMORROW ({tomorrow_name}, {tomorrow_human} — ISO: {tomorrow_iso})")
            elif t == yesterday_iso:
                target_descs.append(f"YESTERDAY ({yesterday_name}, {yesterday_human} — ISO: {yesterday_iso})")
            else:
                try:
                    dt = datetime.strptime(t, "%Y-%m-%d")
                    target_descs.append(f"{dt.strftime('%A, %d %B %Y')} (ISO: {t})")
                except ValueError:
                    target_descs.append(f"Date: {t}")
        requested_context = ", ".join(target_descs)
    else:
        requested_context = f"General Inquiry (Reference date is {today_name}, {today_human})"

    return {
        "today_iso": today_iso,
        "today_human": today_human,
        "today_name": today_name,
        "tomorrow_iso": tomorrow_iso,
        "tomorrow_human": tomorrow_human,
        "tomorrow_name": tomorrow_name,
        "yesterday_iso": yesterday_iso,
        "yesterday_human": yesterday_human,
        "yesterday_name": yesterday_name,
        "target_dates": targets,
        "requested_context": requested_context
    }
