"""
Presence Analytics Engine — Device identification and ownership inference
through behavioral pattern analysis.

Rather than requiring manual device registration, this engine observes
network behavior over time and infers:
  - Which devices belong to the same person (co-occurrence clustering)
  - Which devices are infrastructure vs personal vs communal
  - Who is likely home at any given time
  - Routine patterns and deviations per person-cluster
  - Device manufacturer hints from MAC OUI + randomization detection

The system improves with every scan. Early inferences are low-confidence
guesses; after days/weeks of data, clusters become high-confidence.

Data flow:
  presence-log.json (raw events) → analytics engine → presence-analytics.json
"""
import json

import os

from collections import Counter
from datetime import datetime
from pathlib import Path
from itertools import combinations

from rudy.paths import RUDY_LOGS  # noqa: E402

LOGS_DIR = RUDY_LOGS
LOGS_DIR.mkdir(exist_ok=True)

# Input files (written by presence.py)
PRESENCE_LOG = LOGS_DIR / "presence-log.json"
PRESENCE_CURRENT = LOGS_DIR / "presence-current.json"
PRESENCE_ROUTINES = LOGS_DIR / "presence-routines.json"
PRESENCE_DEVICES = LOGS_DIR / "presence-devices.json"

# Output files (written by this engine)
ANALYTICS_FILE = LOGS_DIR / "presence-analytics.json"
INFERENCE_LOG = LOGS_DIR / "presence-inference-log.json"
HOUSEHOLD_FILE = LOGS_DIR / "presence-household.json"
SNAPSHOTS_DIR = LOGS_DIR / "presence-snapshots"

# --- MAC Address Intelligence ---

# Common OUI prefixes (first 3 octets) → manufacturer
# Only for globally-unique MACs (bit 1 of first byte = 0)
OUI_DB = {
    "f8:bb:bf": "Arris/CommScope (ISP Router)",
    "f8:bb:b3": "Arris/CommScope",
    "00:1a:2b": "Arris",
    "10:56:11": "Arris",
    "44:e1:37": "Arris",
    "9c:3d:cf": "NETGEAR",
    "a0:40:a0": "NETGEAR",
    "50:14:79": "Liteon/Apple (Mac/iPhone/iPad)",
    "3c:22:fb": "Apple",
    "a4:83:e7": "Apple",
    "f0:18:98": "Apple",
    "dc:a6:32": "Raspberry Pi",
    "b8:27:eb": "Raspberry Pi",
    "00:e0:4c": "Realtek (Generic NIC)",
    "ac:12:03": "Intel",
    "48:51:c5": "Intel",
    "70:85:c2": "AzureWave (Mini PC / embedded WiFi)",
    "00:0c:29": "VMware",
    "00:50:56": "VMware",
    "00:15:5d": "Hyper-V",
    "b0:be:76": "TP-Link",
    "ec:08:6b": "TP-Link",
    "60:32:b1": "TP-Link",
    "30:de:4b": "TP-Link",
    "cc:40:d0": "NETGEAR",
    "20:e5:2a": "NETGEAR",
    "00:1e:58": "D-Link",
    "1c:87:2c": "ASUSTek",
    "04:d4:c4": "ASUSTek",
}

DEVICE_TYPE_HINTS = {
    "Arris/CommScope (ISP Router)": "router",
    "Arris/CommScope": "router",
    "Arris": "router",
    "NETGEAR": "networking",
    "Liteon/Apple (Mac/iPhone/iPad)": "apple_device",
    "Apple": "apple_device",
    "Raspberry Pi": "iot",
    "Realtek (Generic NIC)": "computer",
    "Intel": "computer",
    "AzureWave (Mini PC / embedded WiFi)": "computer",
    "VMware": "virtual_machine",
    "Hyper-V": "virtual_machine",
    "TP-Link": "networking",
    "D-Link": "networking",
    "ASUSTek": "computer",
}

def is_mac_randomized(mac: str) -> bool:
    """
    Check if a MAC is locally-administered (randomized).
    Bit 1 of the first octet = 1 means locally administered.
    Modern iOS/Android devices randomize WiFi MACs for privacy.
    """
    first_byte = int(mac.replace("-", ":").split(":")[0], 16)
    return bool(first_byte & 0x02)

def lookup_oui(mac: str) -> dict:
    """Look up manufacturer from MAC OUI (first 3 octets)."""
    normalized = mac.replace("-", ":").lower()
    oui = ":".join(normalized.split(":")[:3])

    if is_mac_randomized(mac):
        return {
            "manufacturer": "Randomized MAC",
            "device_hint": "mobile_device",
            "randomized": True,
            "note": "Modern phone/tablet with MAC privacy enabled",
        }

    mfg = OUI_DB.get(oui, "Unknown")
    return {
        "manufacturer": mfg,
        "device_hint": DEVICE_TYPE_HINTS.get(mfg, "unknown"),
        "randomized": False,
        "note": f"Globally unique MAC — {mfg}" if mfg != "Unknown" else "Unknown manufacturer",
    }

# --- Scan Snapshot System ---
# Each presence scan gets recorded as a snapshot for time-series analysis

class ScanSnapshot:
    """Records what devices were present at a point in time."""

    def __init__(self, timestamp: str, macs_present: set):
        self.timestamp = timestamp
        self.macs = frozenset(macs_present)
        self.hour = datetime.fromisoformat(timestamp).hour
        self.day = datetime.fromisoformat(timestamp).strftime("%A")
        self.date = datetime.fromisoformat(timestamp).strftime("%Y-%m-%d")

# --- Co-Occurrence Analysis ---

def compute_cooccurrence(snapshots: list) -> dict:
    """
    Compute pairwise co-occurrence scores between devices.
    Devices that always appear/disappear together score high.

    Returns: {(mac_a, mac_b): {"jaccard": float, "together": int, "apart": int}}
    """
    pair_together = Counter()
    pair_either = Counter()
    device_count = Counter()

    for snap in snapshots:
        macs = snap.macs
        device_count.update(macs)
        for a, b in combinations(sorted(macs), 2):
            pair_together[(a, b)] += 1

        # Count how often each pair has at least one present
        all_macs = set()
        for s in snapshots:
            all_macs.update(s.macs)
        for a, b in combinations(sorted(all_macs), 2):
            if a in macs or b in macs:
                pair_either[(a, b)] += 1

    scores = {}
    for pair, together in pair_together.items():
        either = pair_either.get(pair, together)
        jaccard = together / either if either > 0 else 0
        # Also compute overlap coefficient: min(P(A|B), P(B|A))
        a, b = pair
        a_count = device_count[a]
        b_count = device_count[b]
        overlap = together / min(a_count, b_count) if min(a_count, b_count) > 0 else 0

        scores[pair] = {
            "jaccard": round(jaccard, 3),
            "overlap": round(overlap, 3),
            "together": together,
            "a_total": a_count,
            "b_total": b_count,
            "total_scans": len(snapshots),
        }

    return scores

# --- Device Classification ---

class DeviceClassifier:
    """Classifies devices based on observed behavior patterns."""

    # Classification thresholds
    ALWAYS_ON_THRESHOLD = 0.90    # Present in 90%+ scans → infrastructure
    MOSTLY_ON_THRESHOLD = 0.70    # Present in 70%+ → communal/always-home
    PERSONAL_RANGE = (0.20, 0.70) # Present 20-70% → personal device
    RARE_THRESHOLD = 0.05         # Present <5% → visitor or intermittent

    def __init__(self, snapshots: list, total_scans: int):
        self.snapshots = snapshots
        self.total_scans = max(total_scans, 1)

    def classify(self, mac: str, device_count: int) -> dict:
        """Classify a single device based on its presence ratio, OUI, and data maturity."""
        presence_ratio = device_count / self.total_scans
        oui = lookup_oui(mac)
        early_stage = self.total_scans < 20  # Not enough data for presence-based classification

        # Start with OUI hint — these are high-confidence regardless of data stage
        if oui["device_hint"] == "router":
            category = "infrastructure"
            confidence = 0.95
        elif oui["device_hint"] == "virtual_machine":
            category = "infrastructure"
            confidence = 0.90
        elif oui["device_hint"] == "networking":
            category = "infrastructure"
            confidence = 0.85
        elif oui["randomized"]:
            # Randomized MAC = modern phone/tablet — this is VERY strong signal
            # Override presence ratio because phones are always-on when home
            category = "personal_mobile"
            confidence = 0.85 if early_stage else 0.75
        elif oui["device_hint"] == "apple_device":
            # Non-randomized Apple = older iPhone/iPad/Mac or Apple TV
            category = "personal_device"
            confidence = 0.70
        elif oui["device_hint"] == "computer":
            # Could be The Workhorse or someone's laptop
            if presence_ratio >= self.ALWAYS_ON_THRESHOLD and not early_stage:
                category = "infrastructure"  # Always-on computer = server
                confidence = 0.75
            else:
                category = "personal_device"
                confidence = 0.60
        elif not early_stage:
            # Only use presence ratio for classification when we have enough data
            if presence_ratio >= self.ALWAYS_ON_THRESHOLD:
                category = "infrastructure"
                confidence = 0.80
            elif presence_ratio >= self.MOSTLY_ON_THRESHOLD:
                category = "communal_or_resident"
                confidence = 0.50
            elif self.PERSONAL_RANGE[0] <= presence_ratio <= self.PERSONAL_RANGE[1]:
                category = "personal_device"
                confidence = 0.60
            elif presence_ratio < self.RARE_THRESHOLD:
                category = "visitor_or_intermittent"
                confidence = 0.40
            else:
                category = "unclassified"
                confidence = 0.20
        else:
            # Early stage, non-randomized, unknown OUI
            category = "unclassified"
            confidence = 0.15

        return {
            "mac": mac,
            "category": category,
            "presence_ratio": round(presence_ratio, 3),
            "confidence": round(confidence, 2),
            "oui": oui,
            "scan_count": device_count,
            "total_scans": self.total_scans,
        }

# --- Person Clustering ---

def cluster_devices_into_persons(cooccurrence: dict, classifications: dict,
                                  min_overlap: float = 0.75) -> list:
    """
    Group devices into person-clusters based on co-occurrence.
    Devices with high overlap coefficient (arrive/depart together) are
    likely owned by the same person.

    Uses simple agglomerative clustering with overlap threshold.
    """
    # Start with each personal device as its own cluster
    personal_macs = [
        mac for mac, cls in classifications.items()
        if cls["category"] in ("personal_mobile", "personal_device",
                                "communal_or_resident", "unclassified")
    ]

    if not personal_macs:
        return []

    # Build adjacency based on co-occurrence
    clusters = [[mac] for mac in personal_macs]

    def find_cluster(mac):
        for i, c in enumerate(clusters):
            if mac in c:
                return i
        return None

    # Merge clusters with high overlap
    for (a, b), scores in sorted(cooccurrence.items(),
                                   key=lambda x: x[1]["overlap"],
                                   reverse=True):
        if scores["overlap"] < min_overlap:
            continue

        ci = find_cluster(a)
        cj = find_cluster(b)
        if ci is not None and cj is not None and ci != cj:
            # Merge smaller into larger
            if len(clusters[ci]) >= len(clusters[cj]):
                clusters[ci].extend(clusters[cj])
                clusters.pop(cj)
            else:
                clusters[cj].extend(clusters[ci])
                clusters.pop(ci)

    # Filter out single-device clusters that are infrastructure
    result = []
    for i, cluster in enumerate(clusters):
        # Score the cluster
        avg_presence = sum(
            classifications[m]["presence_ratio"]
            for m in cluster if m in classifications
        ) / max(len(cluster), 1)

        result.append({
            "cluster_id": i,
            "label": f"Person {i + 1}",  # Placeholder until identified
            "devices": cluster,
            "device_count": len(cluster),
            "avg_presence": round(avg_presence, 3),
            "inferred_resident": avg_presence > 0.40,
        })

    return result

# --- Activity Pattern Analysis ---

def analyze_activity_patterns(routines: dict, mac: str) -> dict:
    """
    Analyze a device's weekly activity pattern.
    Returns sleep hours, peak hours, weekend vs weekday behavior.
    """
    routine = routines.get(mac, {})
    weekly = routine.get("weekly", {})
    total_scans = routine.get("total_scans", 0)

    if total_scans < 5:
        return {"status": "insufficient_data", "total_scans": total_scans}

    # Aggregate hourly activity across all days
    hourly_total = [0] * 24
    weekday_total = [0] * 24
    weekend_total = [0] * 24

    for day, hours in weekly.items():
        for h in range(24):
            hourly_total[h] += hours[h]
            if day in ("Saturday", "Sunday"):
                weekend_total[h] += hours[h]
            else:
                weekday_total[h] += hours[h]

    max_activity = max(hourly_total) if hourly_total else 1

    # Find "quiet hours" — sustained low activity (likely sleep or away)
    quiet_hours = [h for h in range(24) if hourly_total[h] < max_activity * 0.15]
    active_hours = [h for h in range(24) if hourly_total[h] > max_activity * 0.50]

    # Estimate sleep window (longest consecutive quiet stretch)
    sleep_start, sleep_end = _find_longest_quiet_stretch(quiet_hours)

    # Weekend vs weekday difference
    weekday_sum = sum(weekday_total)
    weekend_sum = sum(weekend_total)
    weekday_avg = weekday_sum / 5 if weekday_sum else 0
    weekend_avg = weekend_sum / 2 if weekend_sum else 0

    return {
        "status": "analyzed",
        "total_scans": total_scans,
        "quiet_hours": quiet_hours,
        "active_hours": active_hours,
        "estimated_sleep": {"start": sleep_start, "end": sleep_end},
        "hourly_profile": hourly_total,
        "weekday_avg_activity": round(weekday_avg, 1),
        "weekend_avg_activity": round(weekend_avg, 1),
        "is_always_on": len(quiet_hours) < 3,
        "is_daytime_only": all(h in range(6, 23) for h in active_hours) if active_hours else False,
    }

def _find_longest_quiet_stretch(quiet_hours: list) -> tuple:
    """Find the longest consecutive stretch of quiet hours (wrapping around midnight)."""
    if not quiet_hours:
        return (None, None)

    # Handle wrap-around by doubling the hours
    extended = sorted(quiet_hours) + [h + 24 for h in sorted(quiet_hours)]

    best_start = extended[0]
    best_len = 1
    curr_start = extended[0]
    curr_len = 1

    for i in range(1, len(extended)):
        if extended[i] == extended[i - 1] + 1:
            curr_len += 1
        else:
            if curr_len > best_len:
                best_len = curr_len
                best_start = curr_start
            curr_start = extended[i]
            curr_len = 1

    if curr_len > best_len:
        best_len = curr_len
        best_start = curr_start

    return (best_start % 24, (best_start + best_len) % 24)

# --- Household Profile ---

def build_household_profile(clusters: list, classifications: dict,
                             household_context: dict = None) -> dict:
    """
    Build an overall household profile combining all inference results.
    household_context is optional seed data (e.g., number of residents).
    """
    ctx = household_context or {}
    expected_residents = ctx.get("expected_residents", None)
    location_type = ctx.get("location_type", "unknown")
    residents_info = ctx.get("residents", [])

    infrastructure = [
        mac for mac, cls in classifications.items()
        if cls["category"] == "infrastructure"
    ]

    personal = [
        mac for mac, cls in classifications.items()
        if cls["category"] in ("personal_mobile", "personal_device")
    ]

    communal = [
        mac for mac, cls in classifications.items()
        if cls["category"] == "communal_or_resident"
    ]

    resident_clusters = [c for c in clusters if c.get("inferred_resident")]

    profile = {
        "generated": datetime.now().isoformat(),
        "location": location_type,
        "expected_residents": expected_residents,
        "inferred_resident_count": len(resident_clusters),
        "infrastructure_devices": len(infrastructure),
        "personal_devices": len(personal),
        "communal_devices": len(communal),
        "total_tracked_devices": len(classifications),
        "clusters": clusters,
        "confidence_note": _confidence_note(classifications),
        "residents_context": residents_info,
    }

    # Match clusters to known residents if context provided
    if residents_info and resident_clusters:
        profile["cluster_assignments"] = _try_match_clusters(
            resident_clusters, residents_info, classifications
        )

    return profile

def _confidence_note(classifications: dict) -> str:
    """Generate a human-readable confidence assessment."""
    total = len(classifications)
    if total == 0:
        return "No data yet."

    avg_scans = sum(c["scan_count"] for c in classifications.values()) / total
    if avg_scans < 10:
        return (
            f"Very early data ({int(avg_scans)} scans avg). "
            "Classifications are preliminary guesses. "
            "Accuracy improves significantly after 50+ scans over several days."
        )
    elif avg_scans < 50:
        return (
            f"Moderate data ({int(avg_scans)} scans avg). "
            "Device categories are forming but person-clusters need more data. "
            "Co-occurrence patterns need multiple arrival/departure cycles."
        )
    elif avg_scans < 200:
        return (
            f"Good data ({int(avg_scans)} scans avg). "
            "Device classifications are reliable. Person-clusters are forming. "
            "Routine patterns becoming meaningful."
        )
    else:
        return (
            f"Rich data ({int(avg_scans)} scans avg). "
            "High confidence in device classifications and person clusters. "
            "Routine deviations are now detectable."
        )

def _try_match_clusters(clusters: list, residents: list,
                          classifications: dict) -> list:
    """
    Attempt to match device clusters to known residents.
    Uses heuristics: number of devices, presence ratio, device types.
    """
    assignments = []
    unmatched_clusters = list(range(len(clusters)))
    unmatched_residents = list(range(len(residents)))

    # Simple heuristic matching based on expected behavior
    for ci in list(unmatched_clusters):
        cluster = clusters[ci]
        best_resident = None
        best_score = 0

        for ri in unmatched_residents:
            resident = residents[ri]
            score = 0

            # Tech-savvy people tend to have more devices
            if resident.get("tech_savvy") and cluster["device_count"] >= 2:
                score += 2
            # Elderly tend to have fewer devices
            if resident.get("elderly") and cluster["device_count"] <= 2:
                score += 2
            # High presence → likely a permanent resident
            if resident.get("permanent") and cluster["avg_presence"] > 0.5:
                score += 3
            # Check if device types match expectations
            has_randomized = any(
                classifications.get(m, {}).get("oui", {}).get("randomized")
                for m in cluster["devices"]
            )
            if has_randomized:
                score += 1  # Modern devices suggest active phone user

            if score > best_score:
                best_score = score
                best_resident = ri

        if best_resident is not None and best_score > 1:
            assignments.append({
                "cluster_id": ci,
                "resident_index": best_resident,
                "resident_name": residents[best_resident].get("name", "?"),
                "confidence": min(0.3 + (best_score * 0.1), 0.7),
                "match_score": best_score,
                "note": "Preliminary match — improves with more data",
            })
            unmatched_residents.remove(best_resident)
            unmatched_clusters.remove(ci)

    return assignments

# --- Main Analysis Engine ---

class PresenceAnalytics:
    """
    Main analytics engine. Call run() periodically (e.g., every hour or
    after each presence scan) to update inferences.
    """

    def __init__(self):
        self.event_log = self._load_json(PRESENCE_LOG, [])
        self.current = self._load_json(PRESENCE_CURRENT, {})
        self.routines = self._load_json(PRESENCE_ROUTINES, {})
        self.devices = self._load_json(PRESENCE_DEVICES, {})
        self.analytics = self._load_json(ANALYTICS_FILE, {})
        self.household = self._load_json(HOUSEHOLD_FILE, {})
        self.inference_log = self._load_json(INFERENCE_LOG, [])

    def _load_json(self, path, default):
        if path.exists():
            try:
                with open(path) as f:
                    return json.load(f)
            except Exception:
                pass
        return default

    def _save_json(self, path, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    def run(self, household_context: dict = None) -> dict:
        """
        Run full analytics cycle:
        1. Build scan snapshots from event log
        2. Classify each device
        3. Compute co-occurrence
        4. Cluster into person-groups
        5. Analyze activity patterns
        6. Build household profile
        7. Save everything
        """
        print(f"[Analytics] Running analysis at {datetime.now().strftime('%H:%M:%S')}...")

        # Step 1: Build snapshots from current + historical data
        snapshots = self._build_snapshots()
        print(f"  Built {len(snapshots)} scan snapshots")

        # Step 2: Count device appearances
        device_counts = Counter()
        all_macs = set()
        for snap in snapshots:
            device_counts.update(snap.macs)
            all_macs.update(snap.macs)

        # Also include currently visible devices
        for mac in self.current:
            all_macs.add(mac)
            if mac not in device_counts:
                device_counts[mac] = 1

        print(f"  Tracking {len(all_macs)} unique devices")

        # Step 3: Classify each device
        classifier = DeviceClassifier(snapshots, len(snapshots))
        classifications = {}
        for mac in all_macs:
            classifications[mac] = classifier.classify(mac, device_counts.get(mac, 0))

        # Step 4: Compute co-occurrence
        cooccurrence = compute_cooccurrence(snapshots) if len(snapshots) >= 3 else {}
        print(f"  Computed {len(cooccurrence)} pairwise co-occurrence scores")

        # Step 5: Cluster into persons
        clusters = cluster_devices_into_persons(cooccurrence, classifications)
        print(f"  Identified {len(clusters)} device clusters (potential persons)")

        # Step 6: Activity patterns
        patterns = {}
        for mac in all_macs:
            patterns[mac] = analyze_activity_patterns(self.routines, mac)

        # Step 7: Build household profile
        ctx = household_context or self.household.get("context", {})
        household = build_household_profile(clusters, classifications, ctx)

        # Step 8: Build device profiles (combining all analysis)
        device_profiles = {}
        for mac in all_macs:
            cls = classifications.get(mac, {})
            oui = cls.get("oui", lookup_oui(mac))
            ip = self.current.get(mac, {}).get("ip", "?")
            registered_name = self.devices.get(mac, {}).get("name")

            device_profiles[mac] = {
                "mac": mac,
                "ip": ip,
                "registered_name": registered_name,
                "manufacturer": oui.get("manufacturer", "Unknown"),
                "randomized_mac": oui.get("randomized", False),
                "category": cls.get("category", "unknown"),
                "category_confidence": cls.get("confidence", 0),
                "presence_ratio": cls.get("presence_ratio", 0),
                "scan_count": device_counts.get(mac, 0),
                "activity_pattern": patterns.get(mac, {}),
                "currently_present": mac in self.current,
                "cluster_id": next(
                    (c["cluster_id"] for c in clusters if mac in c["devices"]),
                    None
                ),
            }

        # Step 9: Generate inferences (human-readable insights)
        inferences = self._generate_inferences(
            device_profiles, clusters, cooccurrence, classifications
        )

        # Compile results
        result = {
            "timestamp": datetime.now().isoformat(),
            "scan_count": len(snapshots),
            "device_count": len(all_macs),
            "device_profiles": device_profiles,
            "clusters": clusters,
            "household": household,
            "inferences": inferences,
            "cooccurrence_top": self._top_cooccurrences(cooccurrence, 15),
        }

        # Save
        self.analytics = result
        self._save_json(ANALYTICS_FILE, result)
        self._save_json(HOUSEHOLD_FILE, household)

        # Append to inference log
        self.inference_log.append({
            "timestamp": result["timestamp"],
            "device_count": result["device_count"],
            "cluster_count": len(clusters),
            "inferences_count": len(inferences),
        })
        self.inference_log = self.inference_log[-500:]
        self._save_json(INFERENCE_LOG, self.inference_log)

        print(f"  Generated {len(inferences)} inferences")
        print(f"  Analysis complete. Results in {ANALYTICS_FILE.name}")

        return result

    def _build_snapshots(self) -> list:
        """
        Build time-series snapshots from event log.
        Each snapshot represents the set of devices present at a point in time.
        """
        snapshots = []

        # Current state is always a snapshot
        if self.current:
            snapshots.append(ScanSnapshot(
                datetime.now().isoformat(),
                set(self.current.keys())
            ))

        # Reconstruct historical snapshots from event log
        # Group events by time windows (5-minute buckets)
        if not self.event_log:
            return snapshots

        present_set = set()
        current_window = None

        for event in sorted(self.event_log, key=lambda e: e.get("time", "")):
            t = event.get("time", "")
            if not t:
                continue

            try:
                dt = datetime.fromisoformat(t)
            except Exception:
                continue

            window = dt.strftime("%Y-%m-%dT%H:%M")[:15] + "0"  # 10-min buckets

            if current_window and window != current_window:
                # New window — save previous snapshot
                if present_set:
                    snapshots.append(ScanSnapshot(current_window + ":00", present_set.copy()))

            current_window = window

            if event.get("type") == "arrival":
                present_set.add(event.get("mac", ""))
            elif event.get("type") == "departure":
                present_set.discard(event.get("mac", ""))

        # Save final window
        if present_set and current_window:
            snapshots.append(ScanSnapshot(current_window + ":00", present_set.copy()))

        return snapshots

    def _generate_inferences(self, profiles: dict, clusters: list,
                              cooccurrence: dict, classifications: dict) -> list:
        """Generate human-readable inference statements."""
        inferences = []
        datetime.now()

        # Infrastructure identification
        infra = [p for p in profiles.values() if p["category"] == "infrastructure"]
        if infra:
            names = [f"{p['ip']} ({p['manufacturer']})" for p in infra]
            inferences.append({
                "type": "infrastructure_id",
                "confidence": 0.85,
                "text": f"Infrastructure devices identified: {', '.join(names)}",
                "detail": "These devices are always on or identified as networking equipment.",
            })

        # Randomized MAC detection
        randomized = [p for p in profiles.values() if p["randomized_mac"]]
        if randomized:
            inferences.append({
                "type": "privacy_macs",
                "confidence": 0.90,
                "text": (
                    f"{len(randomized)} devices use randomized MACs "
                    "(modern phones/tablets with WiFi privacy enabled)"
                ),
                "detail": (
                    "Randomized MACs indicate recent iOS or Android devices. "
                    "These are almost certainly personal mobile devices."
                ),
            })

        # Person cluster insights
        for cluster in clusters:
            if cluster["device_count"] > 1:
                macs = cluster["devices"]
                ips = [profiles[m]["ip"] for m in macs if m in profiles]
                inferences.append({
                    "type": "device_cluster",
                    "confidence": 0.50,  # Low initially
                    "text": (
                        f"Cluster '{cluster['label']}': {len(macs)} devices "
                        f"({', '.join(ips)}) appear to belong to the same person"
                    ),
                    "detail": "Based on co-occurrence patterns (arrive/depart together).",
                    "cluster_id": cluster["cluster_id"],
                })

        # Always-present device (could be communal)
        for mac, profile in profiles.items():
            if profile["presence_ratio"] > 0.85 and profile["category"] != "infrastructure":
                inferences.append({
                    "type": "always_present",
                    "confidence": 0.60,
                    "text": (
                        f"Device at {profile['ip']} is present {profile['presence_ratio']*100:.0f}% "
                        f"of the time — likely communal or belongs to someone always home"
                    ),
                    "detail": "Elderly residents or stay-at-home family members often have this pattern.",
                })

        # Co-occurrence pairs
        for (a, b), scores in sorted(cooccurrence.items(),
                                       key=lambda x: x[1]["overlap"],
                                       reverse=True)[:5]:
            if scores["overlap"] > 0.80:
                ip_a = profiles.get(a, {}).get("ip", "?")
                ip_b = profiles.get(b, {}).get("ip", "?")
                inferences.append({
                    "type": "strong_cooccurrence",
                    "confidence": min(0.4 + scores["overlap"] * 0.5, 0.85),
                    "text": (
                        f"Devices {ip_a} and {ip_b} have {scores['overlap']*100:.0f}% "
                        f"co-occurrence — very likely same owner"
                    ),
                })

        # Scan count advisory
        total_scans = max(
            (p.get("scan_count", 0) for p in profiles.values()),
            default=0
        )
        if total_scans < 10:
            inferences.append({
                "type": "data_advisory",
                "confidence": 1.0,
                "text": (
                    f"Only {total_scans} scan(s) recorded. "
                    "Need 50+ scans over several days for reliable person-clustering."
                ),
                "detail": (
                    "The analytics engine improves dramatically with more data. "
                    "After 1 week of 15-minute scans (~672 scans), "
                    "device ownership inference becomes high-confidence."
                ),
            })

        return inferences

    def _top_cooccurrences(self, cooccurrence: dict, n: int) -> list:
        """Return top N co-occurrence pairs for the dashboard."""
        top = sorted(cooccurrence.items(), key=lambda x: x[1]["overlap"], reverse=True)[:n]
        result = []
        for (a, b), scores in top:
            result.append({
                "device_a": a,
                "device_b": b,
                "jaccard": scores["jaccard"],
                "overlap": scores["overlap"],
                "together": scores["together"],
            })
        return result

    def seed_household(self, context: dict):
        """
        Seed the system with known household context.
        This doesn't label devices — it gives the engine hints for better inference.

        Example:
            seed_household({
                "location_type": "family_farm",
                "expected_residents": 4,
                "residents": [
                    {"name": "Chris", "role": "son", "tech_savvy": True, "permanent": False},
                    {"name": "Dad", "role": "patriarch", "elderly": True, "permanent": True, "fall_risk": True},
                    {"name": "Mom", "role": "matriarch", "elderly": True, "permanent": True, "fall_risk": True},
                    {"name": "Katie", "role": "twin_sister", "permanent": False},
                ],
            })
        """
        self.household["context"] = context
        self._save_json(HOUSEHOLD_FILE, self.household)
        print(f"Household context seeded: {context.get('location_type', '?')}, "
              f"{context.get('expected_residents', '?')} expected residents")

    def get_dashboard_data(self) -> dict:
        """Return data formatted for the web dashboard."""
        return {
            "analytics": self.analytics,
            "household": self.household,
            "current_devices": self.current,
            "registered_devices": self.devices,
            "last_updated": self.analytics.get("timestamp", "never"),
        }

    def print_report(self):
        """Print a human-readable analytics report."""
        if not self.analytics:
            print("No analytics data yet. Run analysis first.")
            return

        a = self.analytics
        print("\n" + "=" * 60)
        print("  PRESENCE ANALYTICS REPORT")
        print(f"  {a.get('timestamp', 'N/A')[:19]}")
        print("=" * 60)

        print(f"\n  Devices tracked: {a.get('device_count', 0)}")
        print(f"  Scan snapshots: {a.get('scan_count', 0)}")
        print(f"  Person clusters: {len(a.get('clusters', []))}")

        # Device breakdown
        profiles = a.get("device_profiles", {})
        categories = Counter(p.get("category") for p in profiles.values())
        print("\n  Device Categories:")
        for cat, count in categories.most_common():
            print(f"    {cat}: {count}")

        # Inferences
        inferences = a.get("inferences", [])
        if inferences:
            print(f"\n  Inferences ({len(inferences)}):")
            for inf in inferences:
                conf = inf.get("confidence", 0)
                conf_bar = "#" * int(conf * 10) + "." * (10 - int(conf * 10))
                print(f"    [{conf_bar}] {inf['text']}")

        # Clusters
        clusters = a.get("clusters", [])
        if clusters:
            print("\n  Person Clusters:")
            for c in clusters:
                devices = c.get("devices", [])
                ips = [profiles.get(m, {}).get("ip", "?") for m in devices]
                print(f"    {c['label']}: {len(devices)} devices ({', '.join(ips)})")
                print(f"      Avg presence: {c.get('avg_presence', 0)*100:.0f}%")
                print(f"      Resident: {'Yes' if c.get('inferred_resident') else 'No'}")

        # Household
        h = a.get("household", {})
        if h.get("confidence_note"):
            print(f"\n  Confidence: {h['confidence_note']}")

        print("\n" + "=" * 60)

# --- Convenience Functions ---

def run_analysis(household_context: dict = None):
    """Run a full analytics cycle and print report."""
    engine = PresenceAnalytics()
    if household_context:
        engine.seed_household(household_context)
    engine.run(household_context)
    engine.print_report()
    return engine

def seed_and_analyze():
    """Seed with the Cimino family farm context and run analysis."""
    context = {
        "location_type": "family_farm",
        "expected_residents": 4,
        "residents": [
            {
                "name": "Chris",
                "role": "son",
                "tech_savvy": True,
                "permanent": False,
                "note": "Attorney, travels frequently (Asia). Has The Workhorse mini PC.",
            },
            {
                "name": "Dad",
                "role": "patriarch",
                "elderly": True,
                "permanent": True,
                "fall_risk": True,
                "note": "Elderly patriarch, likely 1-2 devices.",
            },
            {
                "name": "Mom",
                "role": "matriarch",
                "elderly": True,
                "permanent": True,
                "fall_risk": True,
                "note": "Elderly matriarch, likely 1-2 devices.",
            },
            {
                "name": "Katie",
                "role": "twin_sister",
                "permanent": False,
                "note": "Twin sister, visiting the farm.",
            },
        ],
    }
    return run_analysis(context)

if __name__ == "__main__":
    seed_and_analyze()
