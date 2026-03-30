"""Weekly hosts file blocklist update — refreshes DNS-level threat blocking."""
import sys, os, json, time
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

try:
    import httpx
    def fetch(url): return httpx.get(url, timeout=30, follow_redirects=True).text
except ImportError:
    import urllib.request
    def fetch(url):
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.read().decode("utf-8")

from rudy.admin import run_elevated_ps

from rudy.paths import DESKTOP  # noqa: E402
url = "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts"

print("Downloading blocklist...")
content = fetch(url)

domains = set()
for line in content.splitlines():
    line = line.strip()
    if line and not line.startswith("#"):
        parts = line.split()
        if len(parts) >= 2 and parts[0] in ("0.0.0.0", "127.0.0.1"):
            domain = parts[1].strip()
            if domain and domain != "localhost" and "." in domain:
                domains.add(domain)

print(f"Parsed {len(domains):,} domains")

# Generate hosts content
header = f"""# Workhorse Hosts File — Auto-updated {datetime.now().isoformat()[:19]}
# Domains blocked: {len(domains)}
127.0.0.1       localhost
::1             localhost
"""

temp = os.path.join(DESKTOP, "rudy-logs", "_updated_hosts.txt")
with open(temp, "w") as f:
    f.write(header)
    for d in sorted(domains):
        f.write(f"0.0.0.0 {d}\n")

run_elevated_ps(f"""
Copy-Item "{temp}" "C:\Windows\System32\drivers\etc\hosts" -Force
ipconfig /flushdns | Out-Null
""")

os.unlink(temp)
print(f"Hosts file updated: {len(domains):,} domains blocked")

with open(os.path.join(DESKTOP, "rudy-logs", "dns-blocking-status.json"), "w") as f:
    json.dump({"timestamp": datetime.now().isoformat(), "domains_blocked": len(domains)}, f)
