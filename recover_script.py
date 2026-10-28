import json

transcript_path = r"C:\Users\jayant\.gemini\antigravity\brain\d7b80320-8aa1-4111-886a-0305abbe1b81\.system_generated\logs\transcript_full.jsonl"

with open(transcript_path, "r", encoding="utf-8") as f:
    for i, line in enumerate(f):
        if i == 1505:
            d = json.loads(line)
            content = d.get("content", "")
            print("Content length:", len(content))
            start = content.find("[{\"announcement_id\"")
            if start != -1:
                end = content.rfind("]")
                ann_str = content[start:end+1]
                items = json.loads(ann_str)
                print(f"Recovered {len(items)} announcements!")
                with open("recovered_announcements.json", "w", encoding="utf-8") as out:
                    json.dump(items, out, indent=2)
                print("Written to recovered_announcements.json")
            break

