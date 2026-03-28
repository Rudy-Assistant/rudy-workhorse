import pytest
from unittest.mock import patch, MagicMock, mock_open, call
from pathlib import Path
import json
from datetime import datetime, timedelta
from fractions import Fraction

import rudy.photo_intel as mod


@pytest.fixture
def tmp_dirs(tmp_path, monkeypatch):
    """Redirect module path constants to tmp_path."""
    desktop = tmp_path / "Desktop"
    logs = desktop / "rudy-logs"
    photo_dir = desktop / "rudy-data" / "photo-intel"
    cache_dir = photo_dir / "geocode-cache"
    reports_dir = photo_dir / "reports"

    monkeypatch.setattr(mod, "DESKTOP", desktop)
    monkeypatch.setattr(mod, "LOGS", logs)
    monkeypatch.setattr(mod, "PHOTO_DIR", photo_dir)
    monkeypatch.setattr(mod, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(mod, "REPORTS_DIR", reports_dir)

    return {
        "desktop": desktop,
        "logs": logs,
        "photo_dir": photo_dir,
        "cache_dir": cache_dir,
        "reports_dir": reports_dir,
    }


class TestSaveLoadJson:
    """Test JSON utility functions."""

    def test_save_json_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "subdir" / "nested" / "file.json"
        data = {"key": "value", "num": 42}

        mod._save_json(path, data)

        assert path.exists()
        with open(path) as f:
            loaded = json.load(f)
        assert loaded == data

    def test_save_json_with_datetime(self, tmp_path):
        path = tmp_path / "file.json"
        now = datetime(2026, 3, 28, 10, 30, 45)
        data = {"timestamp": now, "nested": {"date": now}}

        mod._save_json(path, data)

        with open(path) as f:
            loaded = json.load(f)
        assert "2026-03-28" in str(loaded)

    def test_load_json_existing_file(self, tmp_path):
        path = tmp_path / "file.json"
        data = {"key": "value"}
        with open(path, "w") as f:
            json.dump(data, f)

        result = mod._load_json(path)
        assert result == data

    def test_load_json_missing_file_returns_default(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        result = mod._load_json(path, default={"default": True})
        assert result == {"default": True}

    def test_load_json_missing_file_empty_dict(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        result = mod._load_json(path)
        assert result == {}

    def test_load_json_invalid_json(self, tmp_path):
        path = tmp_path / "invalid.json"
        path.write_text("not valid json {")
        result = mod._load_json(path, default={"fallback": True})
        assert result == {"fallback": True}


class TestEXIFExtractor:
    """Test EXIF extraction."""

    def test_extract_file_not_found(self):
        extractor = mod.EXIFExtractor()
        result = extractor.extract("/nonexistent/path.jpg")
        assert result["error"] == "File not found: /nonexistent/path.jpg"

    def test_extract_file_metadata_no_pil(self, tmp_path):
        """Test extraction with file metadata but no PIL."""
        image_path = tmp_path / "test.jpg"
        image_path.write_text("fake image")

        extractor = mod.EXIFExtractor()
        with patch.object(extractor, "_get_pil", return_value=None):
            result = extractor.extract(str(image_path))

        assert result["filename"] == "test.jpg"
        assert result["extension"] == ".jpg"
        assert result["size_bytes"] > 0
        assert result["error"] == "Pillow not installed"

    def test_extract_with_pil_no_exif(self, tmp_path):
        """Test extraction with PIL but no EXIF data."""
        image_path = tmp_path / "test.jpg"
        image_path.write_text("fake")

        mock_img = MagicMock()
        mock_img.width = 800
        mock_img.height = 600
        mock_img.format = "JPEG"
        mock_img.mode = "RGB"
        mock_img._getexif.return_value = None

        mock_image_class = MagicMock()
        mock_image_class.open.return_value = mock_img

        extractor = mod.EXIFExtractor()
        with patch.object(extractor, "_get_pil", return_value=(mock_image_class, {}, {})):
            result = extractor.extract(str(image_path))

        assert result["width"] == 800
        assert result["height"] == 600
        assert result["exif"] is None
        assert result["note"] == "No EXIF data found"
        mock_img.close.assert_called_once()

    def test_extract_pil_open_error(self, tmp_path):
        """Test extraction when PIL fails to open image."""
        image_path = tmp_path / "test.jpg"
        image_path.write_text("fake")

        mock_image_class = MagicMock()
        mock_image_class.open.side_effect = Exception("Corrupted image")

        extractor = mod.EXIFExtractor()
        with patch.object(extractor, "_get_pil", return_value=(mock_image_class, {}, {})):
            result = extractor.extract(str(image_path))

        assert "error" in result
        assert "Corrupted image" in result["error"]

    def test_parse_gps_empty(self):
        extractor = mod.EXIFExtractor()
        result = extractor._parse_gps({})
        assert result is None

    def test_parse_gps_missing_coords(self):
        extractor = mod.EXIFExtractor()
        result = extractor._parse_gps({"GPSLatitudeRef": "N"})
        assert result is None

    def test_parse_gps_with_altitude(self):
        extractor = mod.EXIFExtractor()
        gps_info = {
            "GPSLatitude": (Fraction(40, 1), Fraction(45, 1), Fraction(36, 1)),
            "GPSLatitudeRef": "N",
            "GPSLongitude": (Fraction(73, 1), Fraction(58, 1), Fraction(56, 1)),
            "GPSLongitudeRef": "W",
            "GPSAltitude": Fraction(100, 1),
            "GPSAltitudeRef": 0,
        }
        result = extractor._parse_gps(gps_info)
        assert result["latitude"] == pytest.approx(40.760, rel=0.01)
        assert result["longitude"] == pytest.approx(-73.9822, rel=0.01)
        assert result["altitude_m"] == 100.0

    def test_parse_gps_with_altitude_negative(self):
        extractor = mod.EXIFExtractor()
        gps_info = {
            "GPSLatitude": (Fraction(0, 1), Fraction(0, 1), Fraction(0, 1)),
            "GPSLatitudeRef": "S",
            "GPSLongitude": (Fraction(0, 1), Fraction(0, 1), Fraction(0, 1)),
            "GPSLongitudeRef": "E",
            "GPSAltitude": Fraction(500, 1),
            "GPSAltitudeRef": 1,  # Below sea level
        }
        result = extractor._parse_gps(gps_info)
        assert result["altitude_m"] == -500.0

    def test_dms_to_decimal_north(self):
        extractor = mod.EXIFExtractor()
        dms = (Fraction(40, 1), Fraction(45, 1), Fraction(36, 1))
        result = extractor._dms_to_decimal(dms, "N")
        assert result == pytest.approx(40.760, rel=0.01)

    def test_dms_to_decimal_south(self):
        extractor = mod.EXIFExtractor()
        dms = (Fraction(40, 1), Fraction(45, 1), Fraction(36, 1))
        result = extractor._dms_to_decimal(dms, "S")
        assert result == pytest.approx(-40.760, rel=0.01)

    def test_dms_to_decimal_with_fraction(self):
        extractor = mod.EXIFExtractor()
        dms = (Fraction(40, 1), Fraction(45, 1), Fraction(36, 1))
        result = extractor._dms_to_decimal(dms, "N")
        assert result == pytest.approx(40.760, rel=0.01)

    def test_parse_datetime_original(self):
        extractor = mod.EXIFExtractor()
        exif = {"DateTimeOriginal": "2026:03:28 14:30:45"}
        result = extractor._parse_datetime(exif)
        assert result == "2026-03-28T14:30:45"

    def test_parse_datetime_digitized(self):
        extractor = mod.EXIFExtractor()
        exif = {"DateTimeDigitized": "2026:03:28 10:00:00"}
        result = extractor._parse_datetime(exif)
        assert result == "2026-03-28T10:00:00"

    def test_parse_datetime_fallback(self):
        extractor = mod.EXIFExtractor()
        exif = {"DateTime": "2026:03:28 08:00:00"}
        result = extractor._parse_datetime(exif)
        assert result == "2026-03-28T08:00:00"

    def test_parse_datetime_invalid(self):
        extractor = mod.EXIFExtractor()
        exif = {"DateTimeOriginal": "invalid-date"}
        result = extractor._parse_datetime(exif)
        assert result is None

    def test_parse_datetime_missing(self):
        extractor = mod.EXIFExtractor()
        exif = {"SomethingElse": "value"}
        result = extractor._parse_datetime(exif)
        assert result is None

    def test_extract_batch_folder_not_found(self):
        extractor = mod.EXIFExtractor()
        result = extractor.extract_batch("/nonexistent/folder")
        assert len(result) == 1
        assert result[0]["error"] == "Folder not found: /nonexistent/folder"

    def test_extract_batch_no_images(self, tmp_path):
        """Test batch extraction on empty folder."""
        result = mod.EXIFExtractor().extract_batch(str(tmp_path))
        assert result == []

    def test_extract_batch_with_images(self, tmp_path):
        """Test batch extraction with multiple image files."""
        image1 = tmp_path / "photo1.jpg"
        image2 = tmp_path / "photo2.png"
        image3 = tmp_path / "document.txt"

        image1.write_text("fake")
        image2.write_text("fake")
        image3.write_text("not an image")

        extractor = mod.EXIFExtractor()
        with patch.object(extractor, "extract") as mock_extract:
            mock_extract.side_effect = [
                {"filename": "photo1.jpg", "size_bytes": 4},
                {"filename": "photo2.png", "size_bytes": 4},
            ]
            result = extractor.extract_batch(str(tmp_path), recursive=False)

        assert len(result) == 2
        assert result[0]["filename"] == "photo1.jpg"
        assert result[1]["filename"] == "photo2.png"

    def test_extract_batch_recursive(self, tmp_path):
        """Test batch extraction with recursive flag."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        (tmp_path / "photo1.jpg").write_text("fake")
        (subdir / "photo2.jpg").write_text("fake")

        extractor = mod.EXIFExtractor()
        with patch.object(extractor, "extract") as mock_extract:
            mock_extract.return_value = {"filename": "test.jpg"}
            result = extractor.extract_batch(str(tmp_path), recursive=True)

        assert len(result) == 2

    def test_get_pil_caching(self):
        """Test that PIL is cached after first load."""
        extractor = mod.EXIFExtractor()
        assert extractor._pil is None

        with patch.dict("sys.modules", {"PIL": MagicMock(), "PIL.ExifTags": MagicMock()}):
            pil1 = extractor._get_pil()
            pil2 = extractor._get_pil()

        assert pil1 is pil2  # Cached


class TestGeoLocator:
    """Test geolocation functionality."""

    def test_init_creates_cache_dir(self, tmp_dirs):
        """Test that init creates cache directory."""
        mod.GeoLocator()
        assert mod.CACHE_DIR.exists()

    def test_reverse_geocode_cache_hit(self, tmp_dirs):
        """Test that cached results are returned."""
        cache_file = mod.CACHE_DIR / "geocode-cache.json"
        cached_result = {
            "40.76,-73.9822": {
                "latitude": 40.76,
                "longitude": -73.9822,
                "address": "New York, NY",
                "city": "New York",
                "country": "United States",
            }
        }
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "w") as f:
            json.dump(cached_result, f)

        geo = mod.GeoLocator()
        result = geo.reverse_geocode(40.76, -73.9822)

        assert result["address"] == "New York, NY"
        assert result["city"] == "New York"

    def test_reverse_geocode_cache_miss_no_geopy(self, tmp_dirs):
        """Test reverse geocode without geopy installed."""
        geo = mod.GeoLocator()
        with patch.dict("sys.modules", {"geopy": None, "geopy.geocoders": None}):
            result = geo.reverse_geocode(40.0, -73.0)

        assert result["latitude"] == 40.0
        assert result["longitude"] == -73.0
        assert "error" in result

    def test_reverse_geocode_with_geopy(self, tmp_dirs):
        """Test reverse geocode with geopy."""
        mock_location = MagicMock()
        mock_location.address = "Test Address"
        mock_location.raw = {
            "address": {
                "city": "Test City",
                "state": "Test State",
                "country": "Test Country",
                "country_code": "TC",
                "postcode": "12345",
            }
        }

        mock_nominatim_class = MagicMock()
        mock_geolocator = MagicMock()
        mock_geolocator.reverse.return_value = mock_location
        mock_nominatim_class.return_value = mock_geolocator

        geo = mod.GeoLocator()
        with patch.dict("sys.modules", {
            "geopy.geocoders": MagicMock(Nominatim=mock_nominatim_class),
            "geopy.exc": MagicMock(),
        }):
            result = geo.reverse_geocode(40.0, -73.0)

        assert result["address"] == "Test Address"
        assert result["city"] == "Test City"
        assert result["country"] == "Test Country"
        assert result["country_code"] == "TC"

    def test_reverse_geocode_geopy_timeout(self, tmp_dirs):
        """Test reverse geocode when geopy times out."""
        mock_nominatim_class = MagicMock()
        mock_geolocator = MagicMock()
        mock_geolocator.reverse.side_effect = Exception("Timeout")
        mock_nominatim_class.return_value = mock_geolocator

        geo = mod.GeoLocator()
        with patch.dict("sys.modules", {
            "geopy.geocoders": MagicMock(Nominatim=mock_nominatim_class),
            "geopy.exc": MagicMock(),
        }):
            result = geo.reverse_geocode(40.0, -73.0)

        assert "error" in result

    def test_batch_geocode(self, tmp_dirs):
        """Test batch geocoding with rate limiting."""
        geo = mod.GeoLocator()
        coords = [(40.0, -73.0), (34.0, -118.0)]

        with patch.object(geo, "reverse_geocode") as mock_reverse:
            mock_reverse.return_value = {"city": "Test City"}
            with patch("time.sleep"):
                result = geo.batch_geocode(coords)

        assert len(result) == 2
        assert mock_reverse.call_count == 2


class TestPhotoOrganizer:
    """Test photo organization and analysis."""

    def test_init(self):
        """Test PhotoOrganizer initialization."""
        org = mod.PhotoOrganizer()
        assert isinstance(org.exif, mod.EXIFExtractor)
        assert isinstance(org.geo, mod.GeoLocator)

    def test_analyze_folder_empty(self, tmp_path):
        """Test analyze_folder with no photos."""
        org = mod.PhotoOrganizer()
        with patch.object(org.exif, "extract_batch", return_value=[]):
            result = org.analyze_folder(str(tmp_path))

        assert result["total_photos"] == 0
        assert result["with_gps"] == 0
        assert result["with_datetime"] == 0
        assert result["cameras_used"] == []

    def test_analyze_folder_with_photos(self, tmp_path):
        """Test analyze_folder with photos."""
        photos = [
            {
                "filename": "photo1.jpg",
                "gps": {"latitude": 40.0, "longitude": -73.0},
                "datetime_taken": "2026-03-28T10:00:00",
                "camera": {"make": "Canon", "model": "EOS R5"},
            },
            {
                "filename": "photo2.jpg",
                "gps": {"latitude": 40.1, "longitude": -73.1},
                "datetime_taken": "2026-03-29T12:00:00",
                "camera": {"make": "Nikon", "model": "Z9"},
            },
        ]

        org = mod.PhotoOrganizer()
        with patch.object(org.exif, "extract_batch", return_value=photos):
            result = org.analyze_folder(str(tmp_path))

        assert result["total_photos"] == 2
        assert result["with_gps"] == 2
        assert result["with_datetime"] == 2
        assert "Canon EOS R5" in result["cameras_used"]
        assert "Nikon Z9" in result["cameras_used"]
        assert "2026-03-28" in result["by_date"]
        assert "2026-03-29" in result["by_date"]

    def test_detect_events_single_event(self):
        """Test detect_events with all photos in one event."""
        now = datetime.now()
        photos = [
            {
                "filename": f"photo{i}.jpg",
                "datetime_taken": (now + timedelta(minutes=i * 10)).isoformat(),
                "gps": {"latitude": 40.0, "longitude": -73.0},
            }
            for i in range(3)
        ]

        org = mod.PhotoOrganizer()
        events = org.detect_events(photos, time_gap_hours=4)

        assert len(events) == 1
        assert events[0]["photo_count"] == 3

    def test_detect_events_multiple_events(self):
        """Test detect_events with time-separated photos."""
        base = datetime(2026, 3, 28, 10, 0, 0)
        photos = [
            {
                "filename": "photo1.jpg",
                "datetime_taken": base.isoformat(),
                "gps": {"latitude": 40.0, "longitude": -73.0},
            },
            {
                "filename": "photo2.jpg",
                "datetime_taken": (base + timedelta(hours=8)).isoformat(),
                "gps": {"latitude": 40.0, "longitude": -73.0},
            },
        ]

        org = mod.PhotoOrganizer()
        events = org.detect_events(photos, time_gap_hours=4)

        assert len(events) == 2
        assert events[0]["photo_count"] == 1
        assert events[1]["photo_count"] == 1

    def test_detect_events_missing_datetime(self):
        """Test detect_events ignores photos without datetime."""
        photos = [
            {"filename": "photo1.jpg", "gps": {"latitude": 40.0, "longitude": -73.0}},
            {
                "filename": "photo2.jpg",
                "datetime_taken": datetime.now().isoformat(),
                "gps": {"latitude": 40.0, "longitude": -73.0},
            },
        ]

        org = mod.PhotoOrganizer()
        events = org.detect_events(photos)

        assert len(events) == 1

    def test_summarize_event(self):
        """Test event summary generation."""
        base = datetime(2026, 3, 28, 10, 0, 0)
        event_photos = [
            (
                base,
                {
                    "filename": "photo1.jpg",
                    "gps": {"latitude": 40.0, "longitude": -73.0},
                },
            ),
            (
                base + timedelta(minutes=30),
                {
                    "filename": "photo2.jpg",
                    "gps": {"latitude": 40.1, "longitude": -73.1},
                },
            ),
        ]

        org = mod.PhotoOrganizer()
        summary = org._summarize_event(event_photos)

        assert summary["photo_count"] == 2
        assert summary["duration_hours"] == 0.5
        assert summary["date"] == "2026-03-28"
        assert len(summary["gps_points"]) == 2
        assert summary["filenames"] == ["photo1.jpg", "photo2.jpg"]


class TestDuplicateDetector:
    """Test duplicate detection."""

    def test_init(self):
        """Test DuplicateDetector initialization."""
        dd = mod.DuplicateDetector()
        assert dd._imagehash is None

    def test_find_duplicates_no_imagehash(self, tmp_path):
        """Test find_duplicates falls back to MD5 when imagehash unavailable."""
        image1 = tmp_path / "photo1.jpg"
        image2 = tmp_path / "photo2.jpg"
        image1.write_text("same content")
        image2.write_text("same content")

        dd = mod.DuplicateDetector()
        with patch.object(dd, "_get_imagehash", return_value=None):
            result = dd.find_duplicates(str(tmp_path))

        assert len(result) == 1
        assert result[0]["exact"] is True

    def test_find_duplicates_with_imagehash(self, tmp_path):
        """Test find_duplicates with imagehash library."""
        image1 = tmp_path / "photo1.jpg"
        image2 = tmp_path / "photo2.jpg"
        image1.write_text("fake image 1")
        image2.write_text("fake image 2")

        mock_hash1 = MagicMock()
        mock_hash2 = MagicMock()
        mock_hash1.__sub__ = MagicMock(return_value=3)  # Hamming distance

        dd = mod.DuplicateDetector()
        mock_ih = MagicMock()
        mock_image = MagicMock()
        with patch.object(dd, "_get_imagehash", return_value=mock_ih):
            with patch.dict("sys.modules", {"PIL.Image": mock_image}):
                mock_img = MagicMock()
                mock_image.open.return_value = mock_img
                mock_ih.average_hash.side_effect = [mock_hash1, mock_hash2]

                result = dd.find_duplicates(str(tmp_path), threshold=5)

        assert len(result) == 1
        assert result[0]["distance"] == 3
        assert result[0]["exact"] is False

    def test_find_exact_duplicates(self, tmp_path):
        """Test _find_exact_duplicates with MD5."""
        image1 = tmp_path / "photo1.jpg"
        image2 = tmp_path / "photo2.jpg"
        image1.write_text("same")
        image2.write_text("same")

        dd = mod.DuplicateDetector()
        result = dd._find_exact_duplicates(str(tmp_path))

        assert len(result) == 1
        assert result[0]["exact"] is True
        assert result[0]["method"] == "md5"

    def test_find_exact_duplicates_unique_files(self, tmp_path):
        """Test _find_exact_duplicates with unique files."""
        (tmp_path / "photo1.jpg").write_text("content1")
        (tmp_path / "photo2.jpg").write_text("content2")

        dd = mod.DuplicateDetector()
        result = dd._find_exact_duplicates(str(tmp_path))

        assert len(result) == 0


class TestTimelineGenerator:
    """Test timeline generation."""

    def test_init(self):
        """Test TimelineGenerator initialization."""
        tg = mod.TimelineGenerator()
        assert isinstance(tg.organizer, mod.PhotoOrganizer)
        assert isinstance(tg.geo, mod.GeoLocator)

    def test_generate_basic(self, tmp_dirs):
        """Test basic timeline generation."""
        base = datetime(2026, 3, 28, 10, 0, 0)
        analysis = {
            "total_photos": 2,
            "photos": [
                {
                    "filename": "photo1.jpg",
                    "datetime_taken": base.isoformat(),
                    "gps": {"latitude": 40.0, "longitude": -73.0},
                }
            ],
            "cameras_used": ["Canon EOS R5"],
            "date_range": {"earliest": "2026-03-28", "latest": "2026-03-28"},
        }

        tg = mod.TimelineGenerator()
        with patch.object(tg.organizer, "analyze_folder", return_value=analysis):
            with patch.object(tg.organizer, "detect_events", return_value=[]):
                with patch("rudy.photo_intel.datetime") as mock_dt:
                    mock_dt.now.return_value = datetime(2026, 3, 28, 15, 0, 0)
                    result = tg.generate("/fake/folder")

        assert result["title"] == "Photo Timeline"
        assert result["total_photos"] == 2
        assert "report_file" in result

    def test_generate_with_geocoding(self, tmp_dirs):
        """Test timeline generation with geocoding."""
        event = {
            "gps_points": [(40.0, -73.0), (40.1, -73.1)],
            "date": "2026-03-28",
            "time_range": "10:00 - 12:00",
            "photo_count": 2,
        }
        analysis = {
            "total_photos": 2,
            "photos": [],
            "cameras_used": [],
            "date_range": {"earliest": "2026-03-28", "latest": "2026-03-28"},
        }

        tg = mod.TimelineGenerator()
        with patch.object(tg.organizer, "analyze_folder", return_value=analysis):
            with patch.object(tg.organizer, "detect_events", return_value=[event]):
                with patch.object(tg.geo, "reverse_geocode") as mock_geo:
                    mock_geo.return_value = {
                        "city": "New York",
                        "country": "United States",
                    }
                    with patch("rudy.photo_intel.datetime") as mock_dt:
                        mock_dt.now.return_value = datetime(2026, 3, 28, 15, 0, 0)
                        result = tg.generate("/fake/folder", geocode=True)

        assert "events" in result
        assert mock_geo.call_count == 2

    def test_group_by_day(self):
        """Test _group_by_day grouping."""
        events = [
            {"date": "2026-03-28", "photo_count": 2},
            {"date": "2026-03-28", "photo_count": 3},
            {"date": "2026-03-29", "photo_count": 1},
        ]

        tg = mod.TimelineGenerator()
        result = tg._group_by_day(events)

        assert len(result["2026-03-28"]) == 2
        assert len(result["2026-03-29"]) == 1

    def test_to_markdown(self):
        """Test timeline to markdown conversion."""
        timeline = {
            "title": "Vacation 2026",
            "total_photos": 50,
            "date_range": {"earliest": "2026-03-28", "latest": "2026-03-30"},
            "cameras": ["Canon EOS R5", "iPhone 14"],
            "days": {
                "2026-03-28": [
                    {
                        "time_range": "10:00 - 12:00",
                        "photo_count": 20,
                        "duration_hours": 2,
                        "locations": [
                            {"city": "Tokyo", "country": "Japan"},
                        ],
                    }
                ]
            },
        }

        tg = mod.TimelineGenerator()
        md = tg.to_markdown(timeline)

        assert "# Vacation 2026" in md
        assert "2026-03-28 to 2026-03-30" in md
        assert "50 photos" in md
        assert "Canon EOS R5" in md
        assert "Tokyo, Japan" in md
        assert "20 photos" in md

    def test_to_html(self):
        """Test timeline to HTML conversion."""
        timeline = {
            "title": "Trip",
            "total_photos": 30,
            "date_range": {"earliest": "2026-03-28", "latest": "2026-03-28"},
            "cameras": ["Canon"],
            "days": {
                "2026-03-28": [
                    {
                        "time_range": "10:00 - 12:00",
                        "photo_count": 15,
                        "duration_hours": 2.0,
                        "locations": [{"city": "Paris", "country": "France"}],
                    }
                ]
            },
        }

        tg = mod.TimelineGenerator()
        html = tg.to_html(timeline)

        assert "<!DOCTYPE html>" in html
        assert "<title>Trip</title>" in html
        assert "10:00 - 12:00" in html
        assert "Paris, France" in html
        assert "15 photos" in html


class TestPhotoIntel:
    """Test main PhotoIntel interface."""

    def test_init(self):
        """Test PhotoIntel initialization."""
        pi = mod.PhotoIntel()
        assert isinstance(pi.exif, mod.EXIFExtractor)
        assert isinstance(pi.geo, mod.GeoLocator)
        assert isinstance(pi.organizer, mod.PhotoOrganizer)
        assert isinstance(pi.duplicates, mod.DuplicateDetector)
        assert isinstance(pi.timeline_gen, mod.TimelineGenerator)

    def test_analyze_no_geocode(self, tmp_path):
        """Test analyze without geocoding."""
        image_path = tmp_path / "photo.jpg"
        image_path.write_text("fake")

        pi = mod.PhotoIntel()
        with patch.object(pi.exif, "extract") as mock_extract:
            mock_extract.return_value = {
                "filename": "photo.jpg",
                "gps": {"latitude": 40.0, "longitude": -73.0},
            }
            result = pi.analyze(str(image_path), geocode=False)

        assert result["filename"] == "photo.jpg"
        assert "location" not in result

    def test_analyze_with_geocode(self, tmp_path):
        """Test analyze with geocoding."""
        image_path = tmp_path / "photo.jpg"
        image_path.write_text("fake")

        pi = mod.PhotoIntel()
        with patch.object(pi.exif, "extract") as mock_extract:
            mock_extract.return_value = {
                "filename": "photo.jpg",
                "gps": {"latitude": 40.0, "longitude": -73.0},
            }
            with patch.object(pi.geo, "reverse_geocode") as mock_geo:
                mock_geo.return_value = {
                    "address": "NYC",
                    "city": "New York",
                }
                result = pi.analyze(str(image_path), geocode=True)

        assert result["location"]["city"] == "New York"

    def test_analyze_folder(self):
        """Test analyze_folder delegates to organizer."""
        pi = mod.PhotoIntel()
        with patch.object(pi.organizer, "analyze_folder") as mock_analyze:
            mock_analyze.return_value = {"total_photos": 5}
            result = pi.analyze_folder("/fake/folder")

        assert result["total_photos"] == 5
        mock_analyze.assert_called_once_with("/fake/folder")

    def test_timeline(self):
        """Test timeline generation."""
        pi = mod.PhotoIntel()
        with patch.object(pi.timeline_gen, "generate") as mock_gen:
            mock_gen.return_value = {"title": "Test Timeline"}
            result = pi.timeline("/fake/folder", title="Test", geocode=True)

        assert result["title"] == "Test Timeline"
        mock_gen.assert_called_once_with("/fake/folder", "Test", True)

    def test_timeline_markdown(self):
        """Test timeline markdown generation."""
        pi = mod.PhotoIntel()
        with patch.object(pi.timeline_gen, "generate") as mock_gen:
            with patch.object(pi.timeline_gen, "to_markdown") as mock_md:
                mock_gen.return_value = {"title": "Test"}
                mock_md.return_value = "# Test"
                result = pi.timeline_markdown("/fake/folder")

        assert result == "# Test"

    def test_timeline_html(self):
        """Test timeline HTML generation."""
        pi = mod.PhotoIntel()
        with patch.object(pi.timeline_gen, "generate") as mock_gen:
            with patch.object(pi.timeline_gen, "to_html") as mock_html:
                mock_gen.return_value = {"title": "Test"}
                mock_html.return_value = "<!DOCTYPE html>"
                result = pi.timeline_html("/fake/folder")

        assert "<!DOCTYPE html>" in result

    def test_find_duplicates(self):
        """Test find_duplicates delegates to detector."""
        pi = mod.PhotoIntel()
        with patch.object(pi.duplicates, "find_duplicates") as mock_find:
            mock_find.return_value = [{"file1": "a.jpg", "file2": "b.jpg"}]
            result = pi.find_duplicates("/fake/folder", threshold=10)

        assert len(result) == 1
        mock_find.assert_called_once_with("/fake/folder", 10)

    def test_geocode(self):
        """Test geocode delegates to geo."""
        pi = mod.PhotoIntel()
        with patch.object(pi.geo, "reverse_geocode") as mock_geo:
            mock_geo.return_value = {"city": "Paris"}
            result = pi.geocode(48.8, 2.3)

        assert result["city"] == "Paris"

    def test_strip_metadata_success(self, tmp_path):
        """Test strip_metadata with successful operation."""
        image_path = tmp_path / "photo.jpg"
        image_path.write_text("fake")
        output_path = tmp_path / "clean.jpg"

        pi = mod.PhotoIntel()
        mock_image = MagicMock()
        with patch.dict("sys.modules", {"PIL.Image": mock_image}):
            mock_img = MagicMock()
            mock_img.getdata.return_value = []
            mock_img.mode = "RGB"
            mock_img.size = (100, 100)
            mock_image.open.return_value = mock_img
            mock_image.new.return_value = mock_img

            result = pi.strip_metadata(str(image_path), str(output_path))

        assert result["success"] is True
        assert result["output"] == str(output_path)

    def test_strip_metadata_error(self, tmp_path):
        """Test strip_metadata with error."""
        image_path = tmp_path / "photo.jpg"
        image_path.write_text("fake")

        pi = mod.PhotoIntel()
        mock_image = MagicMock()
        with patch.dict("sys.modules", {"PIL.Image": mock_image}):
            mock_image.open.side_effect = Exception("Corrupted")
            result = pi.strip_metadata(str(image_path))

        assert result["success"] is False
        assert "Corrupted" in result["error"]

    def test_get_map_url(self):
        """Test get_map_url generation."""
        pi = mod.PhotoIntel()
        url = pi.get_map_url(40.7128, -74.0060)
        assert "google.com/maps" in url
        assert "40.7128" in url
        assert "-74.006" in url

    def test_get_status_all_capabilities(self):
        """Test get_status with all libraries available."""
        pi = mod.PhotoIntel()
        with patch.dict("sys.modules", {
            "PIL": MagicMock(),
            "geopy.geocoders": MagicMock(),
            "imagehash": MagicMock(),
        }):
            status = pi.get_status()

        assert "exif_extraction" in status["capabilities"]
        assert "geocoding" in status["capabilities"]
        assert "perceptual_hashing" in status["capabilities"]

    def test_get_status_missing_pil(self):
        """Test get_status without PIL."""
        pi = mod.PhotoIntel()
        with patch.dict("sys.modules", {"PIL": None}):
            status = pi.get_status()

        assert "exif_extraction" not in status["capabilities"]

    def test_get_status_fallback_to_md5(self):
        """Test get_status falls back to MD5 without imagehash."""
        pi = mod.PhotoIntel()
        with patch.dict("sys.modules", {"imagehash": None}):
            status = pi.get_status()

        assert "md5_duplicate_detection" in status["capabilities"]


class TestImageExtensions:
    """Test image extension constants."""

    def test_image_extensions_defined(self):
        """Test that image extensions are defined."""
        assert ".jpg" in mod.IMAGE_EXTENSIONS
        assert ".png" in mod.IMAGE_EXTENSIONS
        assert ".heic" in mod.IMAGE_EXTENSIONS
        assert ".raw" in mod.IMAGE_EXTENSIONS

    def test_video_extensions_defined(self):
        """Test that video extensions are defined."""
        assert ".mp4" in mod.VIDEO_EXTENSIONS
        assert ".mov" in mod.VIDEO_EXTENSIONS
        assert ".mkv" in mod.VIDEO_EXTENSIONS
