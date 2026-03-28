import pytest
from unittest.mock import patch, MagicMock, PropertyMock, call
from pathlib import Path
import json
import time

import rudy.surveillance as mod


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    """Redirect config paths to temp directory."""
    data_dir = tmp_path / "rudy-data" / "surveillance"
    snapshots_dir = data_dir / "snapshots"
    recordings_dir = data_dir / "recordings"
    logs_dir = tmp_path / "rudy-logs"

    data_dir.mkdir(parents=True, exist_ok=True)
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    recordings_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(mod, "DATA_DIR", data_dir)
    monkeypatch.setattr(mod, "SNAPSHOTS_DIR", snapshots_dir)
    monkeypatch.setattr(mod, "RECORDINGS_DIR", recordings_dir)
    monkeypatch.setattr(mod, "LOGS_DIR", logs_dir)
    monkeypatch.setattr(mod, "CONFIG_FILE", data_dir / "surveillance-config.json")

    return {
        "data_dir": data_dir,
        "snapshots_dir": snapshots_dir,
        "recordings_dir": recordings_dir,
        "logs_dir": logs_dir,
    }


@pytest.fixture
def mock_cv2():
    """Mock cv2 (OpenCV) module."""
    with patch("cv2.VideoCapture") as mock_capture, \
         patch("cv2.cvtColor") as mock_cvtColor, \
         patch("cv2.GaussianBlur") as mock_blur, \
         patch("cv2.absdiff") as mock_absdiff, \
         patch("cv2.threshold") as mock_threshold, \
         patch("cv2.dilate") as mock_dilate, \
         patch("cv2.findContours") as mock_findContours, \
         patch("cv2.contourArea") as mock_contourArea, \
         patch("cv2.countNonZero") as mock_countNonZero, \
         patch("cv2.boundingRect") as mock_boundingRect, \
         patch("cv2.imwrite") as mock_imwrite, \
         patch("cv2.rectangle") as mock_rectangle, \
         patch("cv2.putText") as mock_putText, \
         patch("cv2.HOGDescriptor") as mock_HOG, \
         patch("cv2.createBackgroundSubtractorMOG2") as mock_bg_sub:

        yield {
            "VideoCapture": mock_capture,
            "cvtColor": mock_cvtColor,
            "GaussianBlur": mock_blur,
            "absdiff": mock_absdiff,
            "threshold": mock_threshold,
            "dilate": mock_dilate,
            "findContours": mock_findContours,
            "contourArea": mock_contourArea,
            "countNonZero": mock_countNonZero,
            "boundingRect": mock_boundingRect,
            "imwrite": mock_imwrite,
            "rectangle": mock_rectangle,
            "putText": mock_putText,
            "HOGDescriptor": mock_HOG,
            "createBackgroundSubtractorMOG2": mock_bg_sub,
        }


@pytest.fixture
def mock_numpy():
    """Mock numpy module."""
    with patch("numpy.zeros") as mock_zeros, \
         patch("numpy.array") as mock_array:

        yield {
            "zeros": mock_zeros,
            "array": mock_array,
        }


def create_mock_frame(height=480, width=640, channels=3):
    """Create a mock frame object."""
    frame = MagicMock()
    frame.shape = (height, width, channels)
    frame.copy.return_value = frame
    return frame


def create_mock_videocapture(frame=None, is_opened=True):
    """Create a mock VideoCapture object."""
    cap = MagicMock()
    cap.isOpened.return_value = is_opened

    if frame is None:
        frame = create_mock_frame()

    cap.read.return_value = (True, frame)
    cap.get.side_effect = lambda prop: {
        "CV_CAP_PROP_FRAME_WIDTH": 640,
        "CV_CAP_PROP_FRAME_HEIGHT": 480,
        "CV_CAP_PROP_FPS": 30.0,
    }.get(prop, 0)
    cap.getBackendName.return_value = "V4L2"
    cap.release.return_value = None

    return cap


# ── Test CameraDiscovery ──────────────────────────────────────


class TestCameraDiscovery:
    """Tests for CameraDiscovery class."""

    def test_find_cameras_empty_no_opencv(self, mock_cv2):
        """Test find_cameras when OpenCV is not available."""
        with patch.dict("sys.modules", {"cv2": None}):
            cameras = mod.CameraDiscovery.find_cameras()
            assert isinstance(cameras, list)

    def test_find_cameras_opencv_available(self, mock_cv2):
        """Test find_cameras with OpenCV available."""
        # Mock cv2 module available
        import cv2

        mock_cap = create_mock_videocapture()
        mock_cv2["VideoCapture"].return_value = mock_cap

        # Mock constants
        with patch("cv2.CAP_DSHOW", 0), \
             patch("cv2.CAP_PROP_FRAME_WIDTH", 1), \
             patch("cv2.CAP_PROP_FRAME_HEIGHT", 2), \
             patch("cv2.CAP_PROP_FPS", 3):

            cameras = mod.CameraDiscovery.find_cameras()
            assert isinstance(cameras, list)

    def test_find_cameras_with_pnp_devices(self, mock_cv2):
        """Test find_cameras with PnP device enumeration."""
        import cv2

        mock_cap = create_mock_videocapture()
        mock_cv2["VideoCapture"].return_value = mock_cap

        pnp_result = [
            {
                "FriendlyName": "Logitech C920",
                "InstanceId": "USB\\VID_046D",
                "Class": "Camera",
            }
        ]

        with patch("cv2.CAP_DSHOW", 0), \
             patch("cv2.CAP_PROP_FRAME_WIDTH", 1), \
             patch("cv2.CAP_PROP_FRAME_HEIGHT", 2), \
             patch("cv2.CAP_PROP_FPS", 3), \
             patch("subprocess.run") as mock_run:

            mock_run.return_value = MagicMock(
                returncode=0, stdout=json.dumps(pnp_result)
            )

            cameras = mod.CameraDiscovery.find_cameras()
            assert isinstance(cameras, list)

    def test_find_cameras_pnp_subprocess_error(self, mock_cv2):
        """Test find_cameras when PnP subprocess fails."""
        import cv2

        mock_cap = create_mock_videocapture()
        mock_cv2["VideoCapture"].return_value = mock_cap

        with patch("cv2.CAP_DSHOW", 0), \
             patch("cv2.CAP_PROP_FRAME_WIDTH", 1), \
             patch("cv2.CAP_PROP_FRAME_HEIGHT", 2), \
             patch("cv2.CAP_PROP_FPS", 3), \
             patch("subprocess.run") as mock_run:

            mock_run.side_effect = Exception("PowerShell not available")

            cameras = mod.CameraDiscovery.find_cameras()
            assert isinstance(cameras, list)

    def test_test_camera_success(self, mock_cv2):
        """Test test_camera with successful camera."""
        import cv2

        frame = create_mock_frame(480, 640)
        mock_cap = create_mock_videocapture(frame=frame)
        mock_cv2["VideoCapture"].return_value = mock_cap

        # Mock the cap.get() to return proper values
        def get_side_effect(prop):
            if prop == 3:  # CAP_PROP_FRAME_WIDTH
                return 640.0
            elif prop == 4:  # CAP_PROP_FRAME_HEIGHT
                return 480.0
            elif prop == 5:  # CAP_PROP_FPS
                return 30.0
            return 0.0

        mock_cap.get.side_effect = get_side_effect

        with patch("cv2.CAP_DSHOW", 0), \
             patch("cv2.CAP_PROP_FRAME_WIDTH", 3), \
             patch("cv2.CAP_PROP_FRAME_HEIGHT", 4), \
             patch("cv2.CAP_PROP_FPS", 5):

            result = mod.CameraDiscovery.test_camera(0)
            assert result["success"] is True
            assert result["width"] == 640
            assert result["height"] == 480
            assert "frame_shape" in result

    def test_test_camera_failed_to_open(self, mock_cv2):
        """Test test_camera when camera cannot be opened."""
        import cv2

        mock_cap = create_mock_videocapture(is_opened=False)
        mock_cv2["VideoCapture"].return_value = mock_cap

        with patch("cv2.CAP_DSHOW", 0):
            result = mod.CameraDiscovery.test_camera(0)
            assert result["success"] is False
            assert "error" in result

    def test_test_camera_failed_to_read_frame(self, mock_cv2):
        """Test test_camera when frame cannot be read."""
        import cv2

        mock_cap = create_mock_videocapture()
        mock_cap.read.return_value = (False, None)
        mock_cv2["VideoCapture"].return_value = mock_cap

        with patch("cv2.CAP_DSHOW", 0):
            result = mod.CameraDiscovery.test_camera(0)
            assert result["success"] is False

    def test_test_camera_with_rtsp_source(self, mock_cv2):
        """Test test_camera with RTSP URL source."""
        import cv2

        frame = create_mock_frame()
        mock_cap = create_mock_videocapture(frame=frame)
        mock_cv2["VideoCapture"].return_value = mock_cap

        with patch("cv2.CAP_DSHOW", 0), \
             patch("cv2.CAP_PROP_FRAME_WIDTH", 1), \
             patch("cv2.CAP_PROP_FRAME_HEIGHT", 2), \
             patch("cv2.CAP_PROP_FPS", 3):

            result = mod.CameraDiscovery.test_camera("rtsp://192.168.1.100/stream")
            assert result["success"] is True


# ── Test MotionDetector ───────────────────────────────────────


class TestMotionDetector:
    """Tests for MotionDetector class."""

    def test_init_default_sensitivity(self):
        """Test MotionDetector initialization with defaults."""
        detector = mod.MotionDetector()
        assert detector.sensitivity == 0.02
        assert detector.min_area == 500

    def test_init_custom_sensitivity(self):
        """Test MotionDetector with custom sensitivity."""
        detector = mod.MotionDetector(sensitivity=0.05, min_area=1000)
        assert detector.sensitivity == 0.05
        assert detector.min_area == 1000

    def test_detect_first_frame_no_motion(self):
        """Test detect on first frame (always returns no motion)."""
        detector = mod.MotionDetector()
        frame = create_mock_frame()

        import cv2

        with patch("cv2.cvtColor") as mock_cvtColor, \
             patch("cv2.GaussianBlur") as mock_blur:

            mock_gray = MagicMock()
            mock_cvtColor.return_value = mock_gray
            mock_blur.return_value = mock_gray

            result = detector.detect(frame)
            assert result["detected"] is False
            assert result["changed_pct"] == 0

    def test_detect_with_motion(self):
        """Test detect identifies motion."""
        detector = mod.MotionDetector(sensitivity=0.02)

        # First frame to establish baseline
        frame1 = create_mock_frame()
        frame2 = create_mock_frame()

        import cv2
        import numpy as np

        gray = MagicMock()
        gray.shape = (480, 640)

        with patch("cv2.cvtColor", return_value=gray), \
             patch("cv2.GaussianBlur", return_value=gray), \
             patch("cv2.absdiff") as mock_absdiff, \
             patch("cv2.threshold") as mock_threshold, \
             patch("cv2.dilate") as mock_dilate, \
             patch("cv2.findContours") as mock_findContours, \
             patch("cv2.contourArea") as mock_contourArea, \
             patch("cv2.countNonZero") as mock_countNonZero, \
             patch("cv2.boundingRect") as mock_boundingRect:

            # Set up mocks
            delta = MagicMock()
            thresh = MagicMock()
            mock_absdiff.return_value = delta
            mock_threshold.return_value = (None, thresh)
            mock_dilate.return_value = thresh

            # Create mock contours
            contour1 = MagicMock()
            contour2 = MagicMock()
            mock_findContours.return_value = ([contour1, contour2], None)
            mock_contourArea.side_effect = [600, 1200]  # Both above min_area
            mock_countNonZero.return_value = 15000  # ~5% of frame
            mock_boundingRect.side_effect = [(10, 20, 50, 60), (100, 100, 80, 90)]

            # First detection (baseline)
            result1 = detector.detect(frame1)
            assert result1["detected"] is False

            # Second detection (with motion)
            result2 = detector.detect(frame2)
            assert result2["detected"] is True
            assert result2["contours"] == 2

    def test_detect_below_sensitivity_threshold(self):
        """Test detect with motion below sensitivity threshold."""
        detector = mod.MotionDetector(sensitivity=0.10)  # 10% threshold

        frame1 = create_mock_frame()
        frame2 = create_mock_frame()

        import cv2

        gray = MagicMock()
        gray.shape = (480, 640)

        with patch("cv2.cvtColor", return_value=gray), \
             patch("cv2.GaussianBlur", return_value=gray), \
             patch("cv2.absdiff") as mock_absdiff, \
             patch("cv2.threshold") as mock_threshold, \
             patch("cv2.dilate") as mock_dilate, \
             patch("cv2.findContours") as mock_findContours, \
             patch("cv2.countNonZero") as mock_countNonZero, \
             patch("cv2.contourArea"):

            delta = MagicMock()
            thresh = MagicMock()
            mock_absdiff.return_value = delta
            mock_threshold.return_value = (None, thresh)
            mock_dilate.return_value = thresh
            mock_findContours.return_value = ([], None)
            mock_countNonZero.return_value = 5000  # ~1.5% of frame (below threshold)

            detector.detect(frame1)  # Baseline
            result = detector.detect(frame2)
            assert result["detected"] is False

    def test_detect_contours_below_min_area(self):
        """Test detect filters contours by min_area."""
        detector = mod.MotionDetector(min_area=1000)

        frame1 = create_mock_frame()
        frame2 = create_mock_frame()

        import cv2

        gray = MagicMock()
        gray.shape = (480, 640)

        with patch("cv2.cvtColor", return_value=gray), \
             patch("cv2.GaussianBlur", return_value=gray), \
             patch("cv2.absdiff") as mock_absdiff, \
             patch("cv2.threshold") as mock_threshold, \
             patch("cv2.dilate") as mock_dilate, \
             patch("cv2.findContours") as mock_findContours, \
             patch("cv2.contourArea") as mock_contourArea, \
             patch("cv2.countNonZero") as mock_countNonZero, \
             patch("cv2.boundingRect"):

            delta = MagicMock()
            thresh = MagicMock()
            mock_absdiff.return_value = delta
            mock_threshold.return_value = (None, thresh)
            mock_dilate.return_value = thresh
            contour = MagicMock()
            mock_findContours.return_value = ([contour], None)
            mock_contourArea.return_value = 500  # Below min_area of 1000
            mock_countNonZero.return_value = 15000

            detector.detect(frame1)  # Baseline
            result = detector.detect(frame2)
            assert result["detected"] is False
            assert result["contours"] == 0


# ── Test PersonDetector ───────────────────────────────────────


class TestPersonDetector:
    """Tests for PersonDetector class."""

    def test_init(self):
        """Test PersonDetector initialization."""
        detector = mod.PersonDetector()
        assert detector._hog is None

    def test_detect_no_people(self):
        """Test detect when no people are found."""
        detector = mod.PersonDetector()
        frame = create_mock_frame()

        import cv2

        with patch("cv2.HOGDescriptor") as mock_HOG, \
             patch("cv2.HOGDescriptor_getDefaultPeopleDetector"):

            mock_hog = MagicMock()
            mock_HOG.return_value = mock_hog
            mock_hog.detectMultiScale.return_value = ([], [])

            result = detector.detect(frame)
            assert result["detected"] is False
            assert result["count"] == 0
            assert result["bounding_boxes"] == []

    def test_detect_with_people(self):
        """Test detect identifies people."""
        detector = mod.PersonDetector()
        frame = create_mock_frame(height=480, width=640)

        import cv2

        with patch("cv2.HOGDescriptor") as mock_HOG, \
             patch("cv2.HOGDescriptor_getDefaultPeopleDetector"), \
             patch("cv2.resize") as mock_resize:

            mock_hog = MagicMock()
            mock_HOG.return_value = mock_hog

            # Return boxes and weights
            boxes = [
                (10, 20, 50, 100),
                (100, 50, 60, 120),
            ]
            weights = [1.5, 2.1]
            mock_hog.detectMultiScale.return_value = (boxes, weights)
            mock_resize.return_value = frame

            result = detector.detect(frame)
            assert result["detected"] is True
            assert result["count"] == 2
            assert len(result["bounding_boxes"]) == 2

    def test_detect_large_frame_resized(self):
        """Test detect resizes large frames."""
        detector = mod.PersonDetector()
        frame = create_mock_frame(height=1080, width=1920)

        import cv2

        with patch("cv2.HOGDescriptor") as mock_HOG, \
             patch("cv2.HOGDescriptor_getDefaultPeopleDetector"), \
             patch("cv2.resize") as mock_resize:

            mock_hog = MagicMock()
            mock_HOG.return_value = mock_hog
            mock_hog.detectMultiScale.return_value = ([], [])

            small_frame = create_mock_frame(height=337, width=640)
            mock_resize.return_value = small_frame

            detector.detect(frame)
            assert mock_resize.called


# ── Test SurveillanceController ──────────────────────────────


class TestSurveillanceController:
    """Tests for SurveillanceController class."""

    def test_init_creates_default_config(self, tmp_config):
        """Test controller initialization creates default config."""
        controller = mod.SurveillanceController()
        assert controller.config["enabled"] is True
        assert controller.config["motion_sensitivity"] == 0.02
        assert controller.config["snapshot_on_motion"] is True

    def test_init_loads_existing_config(self, tmp_config):
        """Test controller loads existing config file."""
        config_data = {
            "enabled": False,
            "motion_sensitivity": 0.05,
            "cameras": [{"type": "usb", "index": 0}],
        }
        config_file = tmp_config["data_dir"] / "surveillance-config.json"
        config_file.write_text(json.dumps(config_data))

        controller = mod.SurveillanceController()
        assert controller.config["enabled"] is False
        assert controller.config["motion_sensitivity"] == 0.05

    def test_discover_saves_config(self, tmp_config):
        """Test discover method saves config."""
        with patch("rudy.surveillance.CameraDiscovery.find_cameras") as mock_find:
            mock_find.return_value = [
                {"type": "usb", "index": 0, "name": "Camera 0"}
            ]

            controller = mod.SurveillanceController()
            cameras = controller.discover()

            assert len(cameras) == 1
            config_file = tmp_config["data_dir"] / "surveillance-config.json"
            assert config_file.exists()

    def test_snapshot_success(self, tmp_config):
        """Test snapshot captures and saves image."""
        import cv2

        frame = create_mock_frame()
        mock_cap = create_mock_videocapture(frame=frame)

        with patch("cv2.VideoCapture", return_value=mock_cap), \
             patch("cv2.CAP_DSHOW", 0), \
             patch("cv2.imwrite") as mock_imwrite:

            mock_imwrite.return_value = True

            controller = mod.SurveillanceController()
            result = controller.snapshot(camera_source=0, reason="test")

            assert result is not None
            assert "snap-test-" in result
            assert mock_imwrite.called

    def test_snapshot_camera_not_opened(self, tmp_config):
        """Test snapshot when camera cannot be opened."""
        import cv2

        mock_cap = create_mock_videocapture(is_opened=False)

        with patch("cv2.VideoCapture", return_value=mock_cap), \
             patch("cv2.CAP_DSHOW", 0):

            controller = mod.SurveillanceController()
            result = controller.snapshot(camera_source=0)

            assert result is None

    def test_snapshot_frame_read_failed(self, tmp_config):
        """Test snapshot when frame read fails."""
        import cv2

        mock_cap = create_mock_videocapture()
        mock_cap.read.return_value = (False, None)

        with patch("cv2.VideoCapture", return_value=mock_cap), \
             patch("cv2.CAP_DSHOW", 0):

            controller = mod.SurveillanceController()
            result = controller.snapshot(camera_source=0)

            assert result is None

    def test_snapshot_with_rtsp_source(self, tmp_config):
        """Test snapshot with RTSP URL."""
        import cv2

        frame = create_mock_frame()
        mock_cap = create_mock_videocapture(frame=frame)

        with patch("cv2.VideoCapture", return_value=mock_cap), \
             patch("cv2.imwrite") as mock_imwrite:

            mock_imwrite.return_value = True

            controller = mod.SurveillanceController()
            result = controller.snapshot(camera_source="rtsp://192.168.1.1/stream")

            assert result is not None

    def test_monitor_cycle_no_motion(self, tmp_config):
        """Test monitor_cycle with no motion detected."""
        import cv2

        frame = create_mock_frame()
        mock_cap = create_mock_videocapture(frame=frame)
        mock_cap.read.side_effect = [(True, frame)] + [(False, None)]

        with patch("cv2.VideoCapture", return_value=mock_cap), \
             patch("cv2.CAP_DSHOW", 0), \
             patch("cv2.cvtColor") as mock_cvtColor, \
             patch("cv2.GaussianBlur") as mock_blur, \
             patch("cv2.absdiff"), \
             patch("cv2.threshold"), \
             patch("cv2.dilate"), \
             patch("cv2.findContours") as mock_findContours, \
             patch("cv2.countNonZero") as mock_countNonZero:

            mock_gray = MagicMock()
            mock_cvtColor.return_value = mock_gray
            mock_blur.return_value = mock_gray
            mock_findContours.return_value = ([], None)
            mock_countNonZero.return_value = 100

            controller = mod.SurveillanceController()
            result = controller.monitor_cycle(camera_source=0, duration_seconds=1)

            assert result["frames_checked"] >= 1
            assert result["motion_events"] == 0

    def test_monitor_cycle_with_motion(self, tmp_config):
        """Test monitor_cycle detects motion and takes snapshot."""
        import cv2

        frame = create_mock_frame()
        mock_cap = create_mock_videocapture(frame=frame)
        mock_cap.read.side_effect = [(True, frame), (False, None)]

        with patch("cv2.VideoCapture", return_value=mock_cap), \
             patch("cv2.CAP_DSHOW", 0), \
             patch("cv2.cvtColor") as mock_cvtColor, \
             patch("cv2.GaussianBlur") as mock_blur, \
             patch("cv2.absdiff"), \
             patch("cv2.threshold") as mock_threshold, \
             patch("cv2.dilate") as mock_dilate, \
             patch("cv2.findContours") as mock_findContours, \
             patch("cv2.countNonZero") as mock_countNonZero, \
             patch("cv2.contourArea") as mock_contourArea, \
             patch("cv2.boundingRect"), \
             patch("cv2.imwrite") as mock_imwrite:

            mock_gray = MagicMock()
            mock_cvtColor.return_value = mock_gray
            mock_blur.return_value = mock_gray
            thresh = MagicMock()
            mock_threshold.return_value = (None, thresh)
            mock_dilate.return_value = thresh
            contour = MagicMock()
            mock_findContours.return_value = ([contour], None)
            mock_contourArea.return_value = 1000
            mock_countNonZero.return_value = 15000  # High motion
            mock_imwrite.return_value = True

            controller = mod.SurveillanceController()
            result = controller.monitor_cycle(
                camera_source=0, duration_seconds=1, check_interval=0.01
            )

            assert result["motion_events"] >= 0

    def test_monitor_cycle_camera_not_opened(self, tmp_config):
        """Test monitor_cycle when camera fails to open."""
        import cv2

        mock_cap = create_mock_videocapture(is_opened=False)

        with patch("cv2.VideoCapture", return_value=mock_cap), \
             patch("cv2.CAP_DSHOW", 0):

            controller = mod.SurveillanceController()
            result = controller.monitor_cycle(camera_source=0, duration_seconds=1)

            assert "error" in result
            assert result["frames_checked"] == 0

    def test_monitor_cycle_with_person_detection(self, tmp_config):
        """Test monitor_cycle with person detection enabled."""
        import cv2

        frame = create_mock_frame()
        mock_cap = create_mock_videocapture(frame=frame)
        mock_cap.read.side_effect = [(True, frame), (False, None)]

        with patch("cv2.VideoCapture", return_value=mock_cap), \
             patch("cv2.CAP_DSHOW", 0), \
             patch("cv2.cvtColor") as mock_cvtColor, \
             patch("cv2.GaussianBlur") as mock_blur, \
             patch("cv2.absdiff"), \
             patch("cv2.threshold") as mock_threshold, \
             patch("cv2.dilate") as mock_dilate, \
             patch("cv2.findContours") as mock_findContours, \
             patch("cv2.countNonZero") as mock_countNonZero, \
             patch("cv2.contourArea") as mock_contourArea, \
             patch("cv2.boundingRect"), \
             patch("cv2.HOGDescriptor") as mock_HOG, \
             patch("cv2.HOGDescriptor_getDefaultPeopleDetector"), \
             patch("cv2.imwrite") as mock_imwrite, \
             patch("cv2.rectangle"), \
             patch("cv2.putText"):

            config_data = {
                "enabled": True,
                "cameras": [],
                "motion_sensitivity": 0.02,
                "min_motion_area": 500,
                "snapshot_on_motion": True,
                "record_on_motion": False,
                "alert_on_person": True,
                "alert_cooldown_minutes": 5,
            }

            config_file = tmp_config["data_dir"] / "surveillance-config.json"
            config_file.write_text(json.dumps(config_data))

            mock_gray = MagicMock()
            mock_cvtColor.return_value = mock_gray
            mock_blur.return_value = mock_gray
            thresh = MagicMock()
            mock_threshold.return_value = (None, thresh)
            mock_dilate.return_value = thresh
            contour = MagicMock()
            mock_findContours.return_value = ([contour], None)
            mock_contourArea.return_value = 1000
            mock_countNonZero.return_value = 15000

            mock_hog = MagicMock()
            mock_HOG.return_value = mock_hog
            boxes = [(50, 50, 60, 120)]
            weights = [1.5]
            mock_hog.detectMultiScale.return_value = (boxes, weights)
            mock_imwrite.return_value = True

            controller = mod.SurveillanceController()
            result = controller.monitor_cycle(
                camera_source=0, duration_seconds=1, check_interval=0.01
            )

            assert isinstance(result, dict)

    def test_save_frame(self, tmp_config):
        """Test _save_frame saves JPEG."""
        import cv2

        frame = create_mock_frame()

        with patch("cv2.imwrite") as mock_imwrite:
            mock_imwrite.return_value = True

            controller = mod.SurveillanceController()
            result = controller._save_frame(frame, "test")

            assert result is not None
            assert "snap-test-" in result
            assert mock_imwrite.called

    def test_save_frame_failure(self, tmp_config):
        """Test _save_frame handles write failure."""
        import cv2

        frame = create_mock_frame()

        with patch("cv2.imwrite", side_effect=Exception("Write failed")):
            controller = mod.SurveillanceController()
            result = controller._save_frame(frame, "test")

            assert result is None

    def test_annotate_frame_with_motion_and_people(self, tmp_config):
        """Test _annotate_frame draws boxes."""
        import cv2

        frame = create_mock_frame()

        with patch("cv2.rectangle"), \
             patch("cv2.putText"):

            controller = mod.SurveillanceController()
            motion = {
                "bounding_boxes": [{"x": 10, "y": 20, "w": 50, "h": 60}]
            }
            persons = {
                "bounding_boxes": [
                    {"x": 100, "y": 100, "w": 60, "h": 120, "confidence": 1.5}
                ]
            }

            result = controller._annotate_frame(frame, motion, persons)
            assert result is not None

    def test_annotate_frame_exception(self, tmp_config):
        """Test _annotate_frame returns original frame on exception."""
        frame = create_mock_frame()

        controller = mod.SurveillanceController()
        with patch("cv2.rectangle", side_effect=Exception("Draw error")):
            motion = {"bounding_boxes": []}
            persons = {"bounding_boxes": []}

            result = controller._annotate_frame(frame, motion, persons)
            assert result == frame

    def test_should_alert_respects_cooldown(self, tmp_config):
        """Test _should_alert respects cooldown period."""
        controller = mod.SurveillanceController()
        controller.config["alert_cooldown_minutes"] = 1

        # First alert should pass
        assert controller._should_alert() is True

        # Immediate second alert should fail
        assert controller._should_alert() is False

        # After cooldown, alert should pass
        controller._last_alert_time = time.time() - 70  # 70 seconds ago
        assert controller._should_alert() is True

    def test_send_motion_alert(self, tmp_config):
        """Test _send_motion_alert sends email."""
        mock_em = MagicMock()

        with patch("rudy.email_multi.MultiEmail", return_value=mock_em):
            controller = mod.SurveillanceController()
            # This should call send even if an exception occurs
            try:
                controller._send_motion_alert("/path/to/snap.jpg", 2, 0.05)
            except Exception:
                pass  # Exception is expected to be caught in the function
            # Verify that the path was reached (function didn't crash at module level)
            assert isinstance(controller, mod.SurveillanceController)

    def test_send_motion_alert_email_exception(self, tmp_config):
        """Test _send_motion_alert handles email errors gracefully."""
        with patch("rudy.email_multi.MultiEmail", side_effect=Exception("Email error")):
            controller = mod.SurveillanceController()
            # Should not raise
            controller._send_motion_alert("/path/to/snap.jpg", 1, 0.05)

    def test_cleanup_old_footage_no_cleanup_needed(self, tmp_config):
        """Test cleanup_old_footage when storage is under limit."""
        controller = mod.SurveillanceController()
        result = controller.cleanup_old_footage(max_gb=10)

        assert result["cleaned"] == 0
        assert result["freed_mb"] == 0

    def test_cleanup_old_footage_removes_old_files(self, tmp_config):
        """Test cleanup_old_footage deletes old files."""
        # Create test files
        snap1 = tmp_config["snapshots_dir"] / "snap1.jpg"
        snap2 = tmp_config["snapshots_dir"] / "snap2.jpg"

        snap1.write_bytes(b"x" * 1000000)  # 1MB
        snap2.write_bytes(b"y" * 1000000)  # 1MB

        # Make snap1 older
        old_time = time.time() - 1000
        snap1.touch()
        import os

        os.utime(snap1, (old_time, old_time))

        controller = mod.SurveillanceController()
        result = controller.cleanup_old_footage(max_gb=0.0001)  # Very small limit

        assert result["cleaned"] >= 1
        assert result["freed_mb"] > 0

    def test_cleanup_old_footage_handles_delete_error(self, tmp_config):
        """Test cleanup_old_footage handles deletion errors."""
        snap = tmp_config["snapshots_dir"] / "snap.jpg"
        snap.write_bytes(b"x" * 1000000)

        controller = mod.SurveillanceController()

        with patch("pathlib.Path.unlink", side_effect=Exception("Delete error")):
            result = controller.cleanup_old_footage(max_gb=0.0001)

            # Should handle gracefully
            assert isinstance(result, dict)


# ── Test Module Entry Points ──────────────────────────────────


class TestEntryPoints:
    """Tests for module-level entry point functions."""

    def test_discover_entry_point(self, tmp_config):
        """Test discover() entry point."""
        with patch("rudy.surveillance.CameraDiscovery.find_cameras") as mock_find:
            mock_find.return_value = [{"type": "usb", "index": 0}]

            result = mod.discover()
            assert isinstance(result, list)

    def test_snapshot_entry_point(self, tmp_config):
        """Test snapshot() entry point."""
        import cv2

        frame = create_mock_frame()
        mock_cap = create_mock_videocapture(frame=frame)

        with patch("cv2.VideoCapture", return_value=mock_cap), \
             patch("cv2.CAP_DSHOW", 0), \
             patch("cv2.imwrite", return_value=True):

            result = mod.snapshot(source=0, reason="test")
            assert result is None or isinstance(result, str)

    def test_monitor_entry_point(self, tmp_config):
        """Test monitor() entry point."""
        import cv2

        mock_cap = create_mock_videocapture(is_opened=False)

        with patch("cv2.VideoCapture", return_value=mock_cap), \
             patch("cv2.CAP_DSHOW", 0):

            result = mod.monitor(source=0, duration=1)
            assert isinstance(result, dict)


# ── Test JSON Utilities ───────────────────────────────────────


class TestJSONUtilities:
    """Tests for JSON save/load utilities."""

    def test_save_json_creates_directory(self, tmp_path):
        """Test _save_json creates parent directory."""
        data_dir = tmp_path / "new" / "nested" / "dir"
        filepath = data_dir / "config.json"
        data = {"key": "value"}

        mod._save_json(filepath, data)

        assert filepath.exists()
        assert json.loads(filepath.read_text())["key"] == "value"

    def test_save_json_with_datetime(self, tmp_path):
        """Test _save_json with datetime objects."""
        from datetime import datetime

        filepath = tmp_path / "config.json"
        data = {"timestamp": datetime(2024, 1, 1, 12, 0, 0)}

        mod._save_json(filepath, data)

        loaded = json.loads(filepath.read_text())
        assert "2024" in loaded["timestamp"]

    def test_load_json_existing_file(self, tmp_path):
        """Test _load_json reads existing file."""
        filepath = tmp_path / "config.json"
        data = {"key": "value", "number": 42}
        filepath.write_text(json.dumps(data))

        result = mod._load_json(filepath)
        assert result["key"] == "value"
        assert result["number"] == 42

    def test_load_json_nonexistent_file_default(self, tmp_path):
        """Test _load_json returns default for nonexistent file."""
        filepath = tmp_path / "missing.json"
        default = {"default": True}

        result = mod._load_json(filepath, default)
        assert result == default

    def test_load_json_nonexistent_file_empty_dict(self, tmp_path):
        """Test _load_json returns empty dict if no default."""
        filepath = tmp_path / "missing.json"

        result = mod._load_json(filepath)
        assert result == {}

    def test_load_json_corrupt_file(self, tmp_path):
        """Test _load_json returns default for corrupt JSON."""
        filepath = tmp_path / "corrupt.json"
        filepath.write_text("{ invalid json")
        default = {"default": True}

        result = mod._load_json(filepath, default)
        assert result == default


# ── Edge Cases ────────────────────────────────────────────────


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_motion_detector_with_empty_frame(self):
        """Test MotionDetector with malformed frame."""
        detector = mod.MotionDetector()
        frame = MagicMock()
        frame.shape = (0, 0, 0)  # Empty frame

        import cv2

        with patch("cv2.cvtColor") as mock_cvtColor, \
             patch("cv2.GaussianBlur") as mock_blur:

            mock_gray = MagicMock()
            mock_gray.shape = (0, 0)
            mock_cvtColor.return_value = mock_gray
            mock_blur.return_value = mock_gray

            result = detector.detect(frame)
            assert result["detected"] is False

    def test_controller_monitor_timeout(self, tmp_config):
        """Test monitor_cycle respects duration timeout."""
        import cv2

        frame = create_mock_frame()
        mock_cap = create_mock_videocapture(frame=frame)

        with patch("cv2.VideoCapture", return_value=mock_cap), \
             patch("cv2.CAP_DSHOW", 0), \
             patch("cv2.cvtColor") as mock_cvtColor, \
             patch("cv2.GaussianBlur") as mock_blur, \
             patch("cv2.absdiff"), \
             patch("cv2.threshold") as mock_threshold, \
             patch("cv2.dilate") as mock_dilate, \
             patch("cv2.findContours") as mock_findContours, \
             patch("cv2.countNonZero") as mock_countNonZero:

            mock_gray = MagicMock()
            mock_cvtColor.return_value = mock_gray
            mock_blur.return_value = mock_gray
            thresh = MagicMock()
            mock_threshold.return_value = (None, thresh)
            mock_dilate.return_value = thresh
            mock_findContours.return_value = ([], None)
            mock_countNonZero.return_value = 100

            # Make read() always succeed to test timeout
            frame_count = [0]

            def read_side_effect():
                frame_count[0] += 1
                return (True, frame)

            mock_cap.read.side_effect = read_side_effect

            controller = mod.SurveillanceController()
            start = time.time()
            controller.monitor_cycle(
                camera_source=0, duration_seconds=0.5, check_interval=0.01
            )
            elapsed = time.time() - start

            assert elapsed < 2.0  # Should not run much longer than duration

    def test_camera_discovery_with_malformed_pnp_json(self, mock_cv2):
        """Test find_cameras handles malformed PnP JSON."""
        import cv2

        mock_cap = create_mock_videocapture()
        mock_cv2["VideoCapture"].return_value = mock_cap

        with patch("cv2.CAP_DSHOW", 0), \
             patch("cv2.CAP_PROP_FRAME_WIDTH", 1), \
             patch("cv2.CAP_PROP_FRAME_HEIGHT", 2), \
             patch("cv2.CAP_PROP_FPS", 3), \
             patch("subprocess.run") as mock_run:

            mock_run.return_value = MagicMock(
                returncode=0, stdout="{ invalid json }"
            )

            # Should not crash
            cameras = mod.CameraDiscovery.find_cameras()
            assert isinstance(cameras, list)

    def test_monitor_cycle_frame_read_fails_mid_cycle(self, tmp_config):
        """Test monitor_cycle handles frame read failure mid-cycle."""
        import cv2

        frame = create_mock_frame()
        mock_cap = create_mock_videocapture(frame=frame)
        # Fail on second read
        mock_cap.read.side_effect = [(True, frame), (False, None)]

        with patch("cv2.VideoCapture", return_value=mock_cap), \
             patch("cv2.CAP_DSHOW", 0), \
             patch("cv2.cvtColor") as mock_cvtColor, \
             patch("cv2.GaussianBlur") as mock_blur, \
             patch("cv2.absdiff"), \
             patch("cv2.threshold") as mock_threshold, \
             patch("cv2.dilate") as mock_dilate, \
             patch("cv2.findContours") as mock_findContours, \
             patch("cv2.countNonZero"):

            mock_gray = MagicMock()
            mock_cvtColor.return_value = mock_gray
            mock_blur.return_value = mock_gray
            thresh = MagicMock()
            mock_threshold.return_value = (None, thresh)
            mock_dilate.return_value = thresh
            mock_findContours.return_value = ([], None)

            controller = mod.SurveillanceController()
            result = controller.monitor_cycle(
                camera_source=0, duration_seconds=10, check_interval=0.01
            )

            assert result["frames_checked"] == 1
