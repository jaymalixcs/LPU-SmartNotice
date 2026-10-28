from app.api.routes.feed import get_affected_classes

res = get_affected_classes("12404501")
print(f"Student: {res['student_name']} (Total checked: {res['timetable_entries_checked']})")
for imp in res['impacts']:
    print(f"  Room: {imp['entry']['room']:8} | Course: {imp['entry']['course_code']:6} | Status: {imp['status']:20} | Affected: {str(imp['affected']):5} | {imp['explanation'][:70]}")

