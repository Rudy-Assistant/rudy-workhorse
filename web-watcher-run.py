import sys, json
from pathlib import Path
from datetime import datetime
sys.path.insert(0, r"C:\Users\C\Desktop")
from rudy.web_intelligence import WebIntelligence

wi = WebIntelligence()
logs = Path(r"C:\Users\C\Desktop\rudy-logs")
today = datetime.now().strftime("%Y-%m-%d_%H%M")

# Check watched URLs
changes = wi.check_watches()

# Search jobs
jobs = wi.search_jobs()

report = {
    "timestamp": datetime.now().isoformat(),
    "page_changes": changes,
    "new_jobs": jobs,
}

with open(logs / f"web-intel-{today}.json", "w") as f:
    json.dump(report, f, indent=2, default=str)

print(f"Web Intelligence Report — {today}")
print(f"  Page changes detected: {len(changes)}")
print(f"  New job listings: {len(jobs)}")
for j in jobs[:5]:
    print(f"    - {j.get('title', '?')} @ {j.get('company', '?')}")
