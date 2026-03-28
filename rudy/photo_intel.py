"""
Photo Intelligence — EXIF metadata analysis, GPS extraction, timeline
generation, and photo organization.

Capabilities:
  1. EXIF metadata extraction from images (GPS, camera, timestamps, etc.)
  2. GPS coordinate → address reverse geocoding
  3. Timeline generation from photo collections (vacation reconstructor)
  4. Duplicate detection via perceptual hashing
  5. Photo organization (by date, location, event, person)
  6. Story/report generation from photo metadata
  7. iCloud photo library analysis (via mounted folder)
  8. Batch metadata operations (strip, add, modify)

Design:
  - Non-destructive: originals never modified unless explicitly requested
  - Works offline: GPS lookup cached, core analysis needs no internet
  - Output: JSON metadata, timeline HTML/markdown, .docx reports
  - Integrates with Canva MCP for visual timeline creation
"""

import json
import logging
import os
import re
import hashlib
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Tuple

log = logging.getLogger(__name__)

DESKTOP = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
LOGS = DESKTOP / "rudy-logs"
PHOTO_DIR = DESKTOP / "rudy-data" / "photo-intel"
CACHE_DIR = PHOTO_DIR / "geocode-cache"
REPORTS_DIR = PHOTO_DIR / "reports"

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".heic", ".heif",
    ".webp", ".bmp", ".gif", ".raw", ".cr2", ".nef", ".arw",
    ".dng", ".orf", ".rw2",
}

VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv", ".m4v", ".3gp", ".wmv",
}


def _save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def _load_json(path: Path, default=None):
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.debug(f"Failed to load JSON from {path}: {e}")
    return default if default is not None else {}


class EXIFExtractor:
    """Extract EXIF metadata from images."""

    def __init__(self):
        self._pil = None

    def _get_pil(self):
        if self._pil is None:
            try:
                from PIL import Image
                from PIL.ExifTags import TAGS, GPSTAGS
                self._pil = (Image, TAGS, GPSTAGS)
            except ImportError:
                pass
        return self._pil

    def extract(self, image_path: str) -> dict:
        """Extract all EXIF data from an image."""
        path = Path(image_path)
        if not path.exists():
            return {"error": f"File not found: {image_path}"}

        result = {
            "file": str(path),
            "filename": path.name,
            "extension": path.suffix.lower(),
            "size_bytes": path.stat().st_size,
            "size_mb": round(path.stat().st_size / (1024 * 1024), 2),
            "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
        }

        pil = self._get_pil()
        if not pil:
            result["error"] = "Pillow not installed"
            return result

        Image, TAGS, GPSTAGS = pil

        try:
            img = Image.open(path)
            result["width"] = img.width
            result["height"] = img.height
            result["format"] = img.format
            result["mode"] = img.mode

            exif_data = img._getexif()
            if exif_data:
                exif = {}
                gps_info = {}

                for tag_id, value in exif_data.items():
                    tag = TAGS.get(tag_id, tag_id)

                    if tag == "GPSInfo":
                        for gps_tag_id, gps_value in value.items():
                            gps_tag = GPSTAGS.get(gps_tag_id, gps_tag_id)
                            gps_info[gps_tag] = gps_value
                    else:
                        # Convert bytes to string for JSON serialization
                        if isinstance(value, bytes):
                            try:
                                value = value.decode(errors="replace")
                            except Exception as e:
                                log.debug(f"Failed to decode EXIF tag value: {e}")
                                value = str(value)
                        exif[str(tag)] = value

                result["exif"] = exif
                result["gps_raw"] = gps_info

                # Parse GPS coordinates
                coords = self._parse_gps(gps_info)
                if coords:
                    result["gps"] = coords

                # Parse datetime
                dt = self._parse_datetime(exif)
                if dt:
                    result["datetime_taken"] = dt

                # Camera info
                result["camera"] = {
                    "make": exif.get("Make", ""),
                    "model": exif.get("Model", ""),
                    "lens": exif.get("LensModel", ""),
                    "focal_length": str(exif.get("FocalLength", "")),
                    "aperture": str(exif.get("FNumber", "")),
                    "iso": exif.get("ISOSpeedRatings", ""),
                    "exposure": str(exif.get("ExposureTime", "")),
                    "flash": str(exif.get("Flash", "")),
                }
            else:
                result["exif"] = None
                result["note"] = "No EXIF data found"

            img.close()
        except Exception as e:
            log.debug(f"EXIF extraction error for {image_path}: {e}")
            result["error"] = str(e)[:200]

        return result

    def _parse_gps(self, gps_info: dict) -> Optional[dict]:
        """Parse GPS EXIF tags into decimal coordinates."""
        if not gps_info:
            return None

        try:
            lat_dms = gps_info.get("GPSLatitude")
            lat_ref = gps_info.get("GPSLatitudeRef", "N")
            lon_dms = gps_info.get("GPSLongitude")
            lon_ref = gps_info.get("GPSLongitudeRef", "E")

            if not lat_dms or not lon_dms:
                return None

            lat = self._dms_to_decimal(lat_dms, lat_ref)
            lon = self._dms_to_decimal(lon_dms, lon_ref)

            result = {"latitude": round(lat, 6), "longitude": round(lon, 6)}

            # Altitude
            alt = gps_info.get("GPSAltitude")
            if alt:
                alt_val = float(alt) if not hasattr(alt, 'numerator') else alt.numerator / alt.denominator
                alt_ref = gps_info.get("GPSAltitudeRef", 0)
                if alt_ref == 1:
                    alt_val = -alt_val
                result["altitude_m"] = round(alt_val, 1)

            return result
        except Exception as e:
            log.debug(f"GPS parsing error: {e}")
            return None

    def _dms_to_decimal(self, dms, ref: str) -> float:
        """Convert degrees/minutes/seconds to decimal."""
        degrees = float(dms[0]) if not hasattr(dms[0], 'numerator') else dms[0].numerator / dms[0].denominator
        minutes = float(dms[1]) if not hasattr(dms[1], 'numerator') else dms[1].numerator / dms[1].denominator
        seconds = float(dms[2]) if not hasattr(dms[2], 'numerator') else dms[2].numerator / dms[2].denominator

        decimal = degrees + minutes / 60 + seconds / 3600
        if ref in ("S", "W"):
            decimal = -decimal
        return decimal

    def _parse_datetime(self, exif: dict) -> Optional[str]:
        """Parse EXIF datetime fields."""
        for field in ["DateTimeOriginal", "DateTimeDigitized", "DateTime"]:
            val = exif.get(field)
            if val:
                try:
                    dt = datetime.strptime(str(val), "%Y:%m:%d %H:%M:%S")
                    return dt.isoformat()
                except ValueError:
                    continue
        return None

    def extract_batch(self, folder: str, recursive: bool = True) -> List[dict]:
        """Extract EXIF from all images in a folder."""
        folder_path = Path(folder)
        if not folder_path.exists():
            return [{"error": f"Folder not found: {folder}"}]

        results = []
        pattern = "**/*" if recursive else "*"
        for f in sorted(folder_path.glob(pattern)):
            if f.suffix.lower() in IMAGE_EXTENSIONS:
                results.append(self.extract(str(f)))

        return results


class GeoLocator:
    """Reverse geocode GPS coordinates to addresses."""

    def __init__(self):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.cache = _load_json(CACHE_DIR / "geocode-cache.json", {})

    def reverse_geocode(self, lat: float, lon: float) -> dict:
        """Convert coordinates to address."""
        cache_key = f"{round(lat, 4)},{round(lon, 4)}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        result = {"latitude": lat, "longitude": lon}

        # Try geopy (Nominatim)
        try:
            from geopy.geocoders import Nominatim
            from geopy.exc import GeocoderTimedOut
            geolocator = Nominatim(user_agent="rudy-photo-intel")
            location = geolocator.reverse(f"{lat}, {lon}", timeout=10)
            if location:
                result["address"] = location.address
                raw = location.raw.get("address", {})
                result["city"] = raw.get("city", raw.get("town", raw.get("village", "")))
                result["state"] = raw.get("state", "")
                result["country"] = raw.get("country", "")
                result["country_code"] = raw.get("country_code", "")
                result["postcode"] = raw.get("postcode", "")
        except ImportError:
            result["error"] = "geopy not installed"
        except Exception as e:
            log.debug(f"Reverse geocoding error for {lat},{lon}: {e}")
            result["error"] = str(e)[:200]

        self.cache[cache_key] = result
        _save_json(CACHE_DIR / "geocode-cache.json", self.cache)
        return result

    def batch_geocode(self, coordinates: List[Tuple[float, float]]) -> List[dict]:
        """Geocode multiple coordinates with rate limiting."""
        results = []
        import time
        for lat, lon in coordinates:
            results.append(self.reverse_geocode(lat, lon))
            time.sleep(1.1)  # Nominatim requires 1 req/sec
        return results


class PhotoOrganizer:
    """Organize photos by date, location, or event."""

    def __init__(self):
        self.exif = EXIFExtractor()
        self.geo = GeoLocator()

    def analyze_folder(self, folder: str, recursive: bool = True) -> dict:
        """Full analysis of a photo folder."""
        photos = self.exif.extract_batch(folder, recursive)

        analysis = {
            "folder": folder,
            "total_photos": len(photos),
            "with_gps": 0,
            "with_datetime": 0,
            "cameras_used": set(),
            "date_range": {"earliest": None, "latest": None},
            "locations": [],
            "by_date": defaultdict(list),
            "by_location": defaultdict(list),
            "photos": photos,
        }

        for p in photos:
            if p.get("gps"):
                analysis["with_gps"] += 1
            if p.get("datetime_taken"):
                analysis["with_datetime"] += 1
                dt = p["datetime_taken"][:10]
                analysis["by_date"][dt].append(p["filename"])
                if not analysis["date_range"]["earliest"] or dt < analysis["date_range"]["earliest"]:
                    analysis["date_range"]["earliest"] = dt
                if not analysis["date_range"]["latest"] or dt > analysis["date_range"]["latest"]:
                    analysis["date_range"]["latest"] = dt

            camera = p.get("camera", {})
            if camera.get("make"):
                cam_str = f"{camera['make']} {camera.get('model', '')}".strip()
                analysis["cameras_used"].add(cam_str)

        # Convert sets to lists for JSON
        analysis["cameras_used"] = list(analysis["cameras_used"])
        analysis["by_date"] = dict(analysis["by_date"])
        analysis["by_location"] = dict(analysis["by_location"])

        return analysis

    def detect_events(self, photos: List[dict],
                      time_gap_hours: int = 4) -> List[dict]:
        """
        Group photos into events based on time gaps.
        Photos taken within time_gap_hours of each other are one event.
        """
        dated = []
        for p in photos:
            dt_str = p.get("datetime_taken")
            if dt_str:
                try:
                    dt = datetime.fromisoformat(dt_str)
                    dated.append((dt, p))
                except ValueError:
                    continue

        dated.sort(key=lambda x: x[0])

        events = []
        current_event = []
        last_time = None

        for dt, photo in dated:
            if last_time and (dt - last_time) > timedelta(hours=time_gap_hours):
                if current_event:
                    events.append(self._summarize_event(current_event))
                current_event = []
            current_event.append((dt, photo))
            last_time = dt

        if current_event:
            events.append(self._summarize_event(current_event))

        return events

    def _summarize_event(self, event_photos: List[Tuple[datetime, dict]]) -> dict:
        """Create event summary from a group of photos."""
        times = [dt for dt, _ in event_photos]
        photos = [p for _, p in event_photos]

        gps_points = []
        for p in photos:
            gps = p.get("gps")
            if gps:
                gps_points.append((gps["latitude"], gps["longitude"]))

        return {
            "start": min(times).isoformat(),
            "end": max(times).isoformat(),
            "duration_hours": round(
                (max(times) - min(times)).total_seconds() / 3600, 1
            ),
            "photo_count": len(photos),
            "date": min(times).strftime("%Y-%m-%d"),
            "time_range": f"{min(times).strftime('%H:%M')} - {max(times).strftime('%H:%M')}",
            "gps_points": gps_points[:20],
            "filenames": [p["filename"] for p in photos],
        }


class DuplicateDetector:
    """Find duplicate photos using perceptual hashing."""

    def __init__(self):
        self._imagehash = None

    def _get_imagehash(self):
        if self._imagehash is None:
            try:
                import imagehash
                self._imagehash = imagehash
            except ImportError:
                pass
        return self._imagehash

    def find_duplicates(self, folder: str, threshold: int = 5) -> List[dict]:
        """
        Find duplicate/near-duplicate images.
        threshold: max hamming distance to consider a match (0=exact, 5=similar).
        """
        ih = self._get_imagehash()
        if not ih:
            # Fallback to file hash (exact duplicates only)
            return self._find_exact_duplicates(folder)

        from PIL import Image

        hashes = {}
        folder_path = Path(folder)

        for f in sorted(folder_path.rglob("*")):
            if f.suffix.lower() in IMAGE_EXTENSIONS:
                try:
                    img = Image.open(f)
                    h = ih.average_hash(img)
                    img.close()
                    hashes[str(f)] = h
                except Exception as e:
                    log.debug(f"Error hashing image {f}: {e}")
                    continue

        # Compare all pairs
        duplicates = []
        files = list(hashes.keys())
        for i in range(len(files)):
            for j in range(i + 1, len(files)):
                distance = hashes[files[i]] - hashes[files[j]]
                if distance <= threshold:
                    duplicates.append({
                        "file1": files[i],
                        "file2": files[j],
                        "distance": distance,
                        "exact": distance == 0,
                    })

        return duplicates

    def _find_exact_duplicates(self, folder: str) -> List[dict]:
        """Fallback: find exact duplicates via MD5."""
        file_hashes = defaultdict(list)
        folder_path = Path(folder)

        for f in sorted(folder_path.rglob("*")):
            if f.suffix.lower() in IMAGE_EXTENSIONS:
                try:
                    h = hashlib.md5(f.read_bytes()).hexdigest()
                    file_hashes[h].append(str(f))
                except Exception as e:
                    log.debug(f"Error computing MD5 hash for {f}: {e}")
                    continue

        duplicates = []
        for h, files in file_hashes.items():
            if len(files) > 1:
                for i in range(len(files)):
                    for j in range(i + 1, len(files)):
                        duplicates.append({
                            "file1": files[i],
                            "file2": files[j],
                            "distance": 0,
                            "exact": True,
                            "method": "md5",
                        })

        return duplicates


class TimelineGenerator:
    """Generate timelines from photo collections."""

    def __init__(self):
        self.organizer = PhotoOrganizer()
        self.geo = GeoLocator()

    def generate(self, folder: str, title: str = "Photo Timeline",
                 geocode: bool = True) -> dict:
        """
        Generate a complete timeline from a folder of photos.
        Returns structured data suitable for rendering as HTML/markdown/Canva.
        """
        analysis = self.organizer.analyze_folder(folder)
        events = self.organizer.detect_events(analysis["photos"])

        # Geocode GPS points in events
        if geocode:
            for event in events:
                for lat, lon in event.get("gps_points", [])[:3]:
                    loc = self.geo.reverse_geocode(lat, lon)
                    if loc.get("city"):
                        if "locations" not in event:
                            event["locations"] = []
                        event["locations"].append({
                            "city": loc["city"],
                            "country": loc.get("country", ""),
                            "lat": lat,
                            "lon": lon,
                        })

        timeline = {
            "title": title,
            "generated": datetime.now().isoformat(),
            "total_photos": analysis["total_photos"],
            "date_range": analysis["date_range"],
            "cameras": analysis["cameras_used"],
            "events": events,
            "days": self._group_by_day(events),
        }

        # Save timeline
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_title = re.sub(r'[^\w\-]', '_', title)
        report_file = REPORTS_DIR / f"timeline-{safe_title}-{timestamp}.json"
        _save_json(report_file, timeline)
        timeline["report_file"] = str(report_file)

        return timeline

    def _group_by_day(self, events: List[dict]) -> dict:
        """Group events by calendar day."""
        days = defaultdict(list)
        for event in events:
            day = event.get("date", "unknown")
            days[day].append(event)
        return dict(days)

    def to_markdown(self, timeline: dict) -> str:
        """Convert timeline to markdown format."""
        lines = []
        lines.append(f"# {timeline['title']}")
        lines.append("")
        dr = timeline.get("date_range", {})
        lines.append(
            f"**{dr.get('earliest', '?')} to {dr.get('latest', '?')}** "
            f"| {timeline['total_photos']} photos"
        )
        if timeline.get("cameras"):
            lines.append(f"Cameras: {', '.join(timeline['cameras'])}")
        lines.append("")

        for day, events in sorted(timeline.get("days", {}).items()):
            lines.append(f"## {day}")
            lines.append("")

            for event in events:
                time_range = event.get("time_range", "")
                count = event.get("photo_count", 0)
                locations = event.get("locations", [])
                loc_str = ""
                if locations:
                    loc_names = list(set(
                        f"{loc['city']}, {loc['country']}" for loc in locations
                    ))
                    loc_str = f" — {', '.join(loc_names)}"

                lines.append(f"### {time_range}{loc_str}")
                lines.append(f"{count} photos")
                duration = event.get("duration_hours", 0)
                if duration > 0:
                    lines.append(f"Duration: {duration} hours")
                lines.append("")

        return "\n".join(lines)

    def to_html(self, timeline: dict) -> str:
        """Convert timeline to a standalone HTML page with visual layout."""
        events_html = []
        for day, events in sorted(timeline.get("days", {}).items()):
            day_events = []
            for event in events:
                locations = event.get("locations", [])
                loc_str = ""
                if locations:
                    loc_names = list(set(
                        f"{loc['city']}, {loc['country']}" for loc in locations
                    ))
                    loc_str = " &mdash; " + ", ".join(loc_names)

                day_events.append(f"""
                <div class="event">
                    <div class="event-time">{event.get('time_range', '')}{loc_str}</div>
                    <div class="event-detail">{event.get('photo_count', 0)} photos
                    {"(" + str(event.get('duration_hours', 0)) + " hrs)" if event.get('duration_hours', 0) > 0 else ""}</div>
                </div>""")

            events_html.append(f"""
            <div class="day">
                <h2>{day}</h2>
                {''.join(day_events)}
            </div>""")

        dr = timeline.get("date_range", {})
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{timeline['title']}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: linear-gradient(135deg, #0f172a, #1e293b);
    color: #e2e8f0;
    min-height: 100vh;
    padding: 2rem;
  }}
  .container {{ max-width: 800px; margin: 0 auto; }}
  h1 {{
    font-size: 2rem;
    background: linear-gradient(90deg, #60a5fa, #a78bfa);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 0.5rem;
  }}
  .meta {{ color: #94a3b8; margin-bottom: 2rem; }}
  .day {{
    background: rgba(255,255,255,0.05);
    border-radius: 12px;
    padding: 1.5rem;
    margin-bottom: 1rem;
    border-left: 3px solid #60a5fa;
  }}
  .day h2 {{ color: #60a5fa; font-size: 1.2rem; margin-bottom: 1rem; }}
  .event {{
    padding: 0.75rem 0;
    border-bottom: 1px solid rgba(255,255,255,0.05);
  }}
  .event:last-child {{ border-bottom: none; }}
  .event-time {{ font-weight: 600; color: #f1f5f9; }}
  .event-detail {{ color: #94a3b8; font-size: 0.9rem; margin-top: 0.25rem; }}
</style>
</head>
<body>
<div class="container">
  <h1>{timeline['title']}</h1>
  <div class="meta">
    {dr.get('earliest', '?')} to {dr.get('latest', '?')} |
    {timeline['total_photos']} photos
    {(' | Cameras: ' + ', '.join(timeline['cameras'])) if timeline.get('cameras') else ''}
  </div>
  {''.join(events_html)}
</div>
</body>
</html>"""
        return html


class PhotoIntel:
    """
    Unified photo intelligence interface.

    Usage:
        pi = PhotoIntel()

        # Analyze a single photo
        info = pi.analyze("vacation/IMG_0001.jpg")

        # Generate a vacation timeline
        timeline = pi.timeline("vacation/", title="Japan Trip 2026")

        # Find duplicates
        dupes = pi.find_duplicates("photos/")

        # Full folder analysis
        analysis = pi.analyze_folder("photos/")
    """

    def __init__(self):
        self.exif = EXIFExtractor()
        self.geo = GeoLocator()
        self.organizer = PhotoOrganizer()
        self.duplicates = DuplicateDetector()
        self.timeline_gen = TimelineGenerator()

    def analyze(self, image_path: str, geocode: bool = True) -> dict:
        """Full analysis of a single photo."""
        result = self.exif.extract(image_path)

        if geocode and result.get("gps"):
            gps = result["gps"]
            location = self.geo.reverse_geocode(gps["latitude"], gps["longitude"])
            result["location"] = location

        return result

    def analyze_folder(self, folder: str) -> dict:
        """Analyze all photos in a folder."""
        return self.organizer.analyze_folder(folder)

    def timeline(self, folder: str, title: str = "Photo Timeline",
                 geocode: bool = True) -> dict:
        """Generate a timeline from a photo folder."""
        return self.timeline_gen.generate(folder, title, geocode)

    def timeline_markdown(self, folder: str, title: str = "Photo Timeline") -> str:
        """Generate markdown timeline."""
        tl = self.timeline_gen.generate(folder, title)
        return self.timeline_gen.to_markdown(tl)

    def timeline_html(self, folder: str, title: str = "Photo Timeline") -> str:
        """Generate HTML timeline."""
        tl = self.timeline_gen.generate(folder, title)
        return self.timeline_gen.to_html(tl)

    def find_duplicates(self, folder: str, threshold: int = 5) -> List[dict]:
        """Find duplicate photos."""
        return self.duplicates.find_duplicates(folder, threshold)

    def geocode(self, lat: float, lon: float) -> dict:
        """Reverse geocode coordinates."""
        return self.geo.reverse_geocode(lat, lon)

    def strip_metadata(self, image_path: str, output_path: str = None) -> dict:
        """Strip all EXIF metadata from an image (privacy)."""
        try:
            from PIL import Image
            img = Image.open(image_path)
            data = list(img.getdata())
            clean = Image.new(img.mode, img.size)
            clean.putdata(data)
            out = output_path or image_path
            clean.save(out)
            return {"success": True, "output": out}
        except Exception as e:
            return {"success": False, "error": str(e)[:200]}

    def get_map_url(self, lat: float, lon: float) -> str:
        """Generate a Google Maps URL for coordinates."""
        return f"https://www.google.com/maps?q={lat},{lon}"

    def get_status(self) -> dict:
        """Check available capabilities."""
        status = {"capabilities": []}

        try:
            from PIL import Image
            status["capabilities"].append("exif_extraction")
        except ImportError:
            pass

        try:
            from geopy.geocoders import Nominatim
            status["capabilities"].append("geocoding")
        except ImportError:
            pass

        try:
            import imagehash
            status["capabilities"].append("perceptual_hashing")
        except ImportError:
            status["capabilities"].append("md5_duplicate_detection")

        return status


if __name__ == "__main__":
    print("Photo Intelligence Module")
    pi = PhotoIntel()

    print("\n  Capabilities:")
    status = pi.get_status()
    for cap in status["capabilities"]:
        print(f"    + {cap}")

    print("\n  Usage:")
    print("    pi = PhotoIntel()")
    print('    info = pi.analyze("path/to/photo.jpg")')
    print('    timeline = pi.timeline("vacation-folder/", title="Japan 2026")')
    print('    dupes = pi.find_duplicates("photos/")')
