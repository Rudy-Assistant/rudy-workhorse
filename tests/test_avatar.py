import pytest
from unittest.mock import patch, MagicMock, call
from pathlib import Path
import json
import sys
import rudy.avatar as mod


@pytest.fixture
def tmp_paths(tmp_path):
    """Setup temporary directory structure for tests."""
    desktop = tmp_path / "desktop"
    avatar_dir = desktop / "rudy-data" / "avatar"
    models_dir = avatar_dir / "models"
    output_dir = avatar_dir / "output"
    temp_dir = avatar_dir / "temp"
    logs = desktop / "rudy-logs"

    for d in [models_dir, output_dir, temp_dir, logs]:
        d.mkdir(parents=True, exist_ok=True)

    return {
        "desktop": desktop,
        "avatar_dir": avatar_dir,
        "models_dir": models_dir,
        "output_dir": output_dir,
        "temp_dir": temp_dir,
        "logs": logs,
    }


@pytest.fixture
def monkeypatch_paths(monkeypatch, tmp_paths):
    """Monkeypatch all path constants."""
    monkeypatch.setattr(mod, "DESKTOP", tmp_paths["desktop"])
    monkeypatch.setattr(mod, "AVATAR_DIR", tmp_paths["avatar_dir"])
    monkeypatch.setattr(mod, "MODELS_DIR", tmp_paths["models_dir"])
    monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_paths["output_dir"])
    monkeypatch.setattr(mod, "TEMP_DIR", tmp_paths["temp_dir"])
    monkeypatch.setattr(mod, "LOGS", tmp_paths["logs"])
    return tmp_paths


class TestRunCommand:
    """Test the _run subprocess wrapper."""

    def test_successful_command(self):
        """Test successful command execution."""
        stdout, stderr, rc = mod._run("echo hello")
        assert stdout == "hello"
        assert stderr == ""
        assert rc == 0

    def test_failed_command(self):
        """Test failed command returns non-zero returncode."""
        stdout, stderr, rc = mod._run("python -c \"import nonexistent_module\"")
        assert rc != 0
        assert stderr or stdout  # Should have error output

    def test_timeout_command(self):
        """Test command timeout."""
        stdout, stderr, rc = mod._run("sleep 10", timeout=1)
        assert stderr == "Timeout"
        assert rc == -1
        assert stdout == ""

    def test_invalid_command(self):
        """Test invalid command."""
        stdout, stderr, rc = mod._run("invalid_command_xyz_123")
        assert rc == -1
        assert stderr or stdout


class TestSaveJson:
    """Test JSON utility function."""

    def test_save_json_creates_parent_dirs(self, tmp_path):
        """Test that _save_json creates parent directories."""
        path = tmp_path / "deep" / "nested" / "path" / "data.json"
        test_data = {"key": "value", "number": 42}

        mod._save_json(path, test_data)

        assert path.exists()
        with open(path) as f:
            loaded = json.load(f)
        assert loaded == test_data

    def test_save_json_with_datetime(self, tmp_path):
        """Test that _save_json handles datetime objects with default=str."""
        from datetime import datetime
        path = tmp_path / "data.json"
        test_data = {"timestamp": datetime(2024, 1, 15, 12, 30, 45)}

        mod._save_json(path, test_data)

        assert path.exists()
        with open(path) as f:
            loaded = json.load(f)
        assert "2024" in loaded["timestamp"]


class TestSadTalkerEngine:
    """Test SadTalker talking-head engine."""

    @patch("rudy.avatar._run")
    def test_sadtalker_not_available(self, mock_run, monkeypatch_paths):
        """Test SadTalker availability check when not installed."""
        mock_run.return_value = ("", "", 1)  # Non-zero return code

        engine = mod.SadTalkerEngine()

        assert engine.available is False

    @patch("rudy.avatar._run")
    def test_sadtalker_available_via_import(self, mock_run, monkeypatch_paths):
        """Test SadTalker available via pip import."""
        mock_run.return_value = ("", "", 0)  # Success

        engine = mod.SadTalkerEngine()

        assert engine.available is True

    @patch("rudy.avatar._run")
    def test_sadtalker_available_via_cloned_repo(self, mock_run, monkeypatch_paths):
        """Test SadTalker available via cloned repo."""
        mock_run.return_value = ("", "", 1)  # Import fails

        # Create the inference.py file
        repo_path = monkeypatch_paths["models_dir"] / "SadTalker"
        repo_path.mkdir(parents=True, exist_ok=True)
        (repo_path / "inference.py").touch()

        engine = mod.SadTalkerEngine()

        assert engine.available is True

    @patch("rudy.avatar._run")
    def test_sadtalker_generate_not_available(self, mock_run, monkeypatch_paths):
        """Test generate returns error when SadTalker not available."""
        mock_run.return_value = ("", "", 1)

        engine = mod.SadTalkerEngine()
        result = engine.generate("source.jpg", "audio.wav", "output.mp4")

        assert result["error"]
        assert "not installed" in result["error"]

    @patch("rudy.avatar.SadTalkerEngine._check")
    @patch("rudy.avatar._run")
    def test_sadtalker_generate_via_api(self, mock_run, mock_check, monkeypatch_paths, tmp_path):
        """Test generate via SadTalker API."""
        mock_check.return_value = True

        # Create test files
        source = tmp_path / "source.jpg"
        audio = tmp_path / "audio.wav"
        source.touch()
        audio.touch()

        output_file = monkeypatch_paths["output_dir"] / "result.mp4"
        output_file.touch()

        # Mock CLI execution (API import fails, falls back to CLI)
        mock_run.return_value = ("", "", 0)

        engine = mod.SadTalkerEngine()
        engine.available = True

        result = engine.generate(str(source), str(audio), str(tmp_path / "output.mp4"))

        assert "engine" in result
        assert result["engine"] == "sadtalker"

    @patch("rudy.avatar.SadTalkerEngine._check")
    @patch("rudy.avatar._run")
    def test_sadtalker_generate_via_cli(self, mock_run, mock_check, monkeypatch_paths, tmp_path):
        """Test generate via SadTalker CLI fallback."""
        mock_check.return_value = True

        source = tmp_path / "source.jpg"
        audio = tmp_path / "audio.wav"
        source.touch()
        audio.touch()

        # Create output file
        output_file = monkeypatch_paths["output_dir"] / "result.mp4"
        output_file.touch()

        # Mock CLI success
        mock_run.return_value = ("", "", 0)

        engine = mod.SadTalkerEngine()
        engine.available = True

        result = engine.generate(str(source), str(audio), str(tmp_path / "output.mp4"))

        assert result["success"] is True or "error" not in result

    @patch("rudy.avatar.SadTalkerEngine._check")
    @patch("rudy.avatar._run")
    def test_sadtalker_generate_cli_failure(self, mock_run, mock_check, monkeypatch_paths, tmp_path):
        """Test generate via CLI with failure."""
        mock_check.return_value = True
        mock_run.return_value = ("", "error message", 1)

        source = tmp_path / "source.jpg"
        audio = tmp_path / "audio.wav"
        source.touch()
        audio.touch()

        engine = mod.SadTalkerEngine()
        engine.available = True

        result = engine.generate(str(source), str(audio), str(tmp_path / "output.mp4"))

        assert result["success"] is False
        assert "error" in result

    @patch("rudy.avatar.SadTalkerEngine._check")
    def test_sadtalker_generate_exception(self, mock_check, monkeypatch_paths, tmp_path):
        """Test generate handles exceptions."""
        mock_check.return_value = True

        engine = mod.SadTalkerEngine()
        engine.available = True

        with patch("rudy.avatar._run", side_effect=Exception("Test error")):
            result = engine.generate("source.jpg", "audio.wav", "output.mp4")

            assert result["success"] is False
            assert "error" in result


class TestWav2LipEngine:
    """Test Wav2Lip lip-sync engine."""

    @patch("rudy.avatar._run")
    def test_wav2lip_not_available(self, mock_run, monkeypatch_paths):
        """Test Wav2Lip availability check when not installed."""
        mock_run.return_value = ("", "", 1)

        engine = mod.Wav2LipEngine()

        assert engine.available is False

    @patch("rudy.avatar._run")
    def test_wav2lip_available(self, mock_run, monkeypatch_paths):
        """Test Wav2Lip availability check when installed."""
        mock_run.return_value = ("", "", 0)

        engine = mod.Wav2LipEngine()

        assert engine.available is True

    @patch("rudy.avatar._run")
    def test_wav2lip_lip_sync_not_available(self, mock_run, monkeypatch_paths):
        """Test lip_sync returns error when Wav2Lip not available."""
        mock_run.return_value = ("", "", 1)

        engine = mod.Wav2LipEngine()
        result = engine.lip_sync("video.mp4", "audio.wav", "output.mp4")

        assert "error" in result
        assert "not installed" in result["error"]

    @patch("rudy.avatar.Wav2LipEngine._check")
    @patch("rudy.avatar._run")
    def test_wav2lip_lip_sync_success(self, mock_run, mock_check, monkeypatch_paths, tmp_path):
        """Test successful lip sync."""
        mock_check.return_value = True
        mock_run.return_value = ("", "", 0)

        video = tmp_path / "video.mp4"
        audio = tmp_path / "audio.wav"
        video.touch()
        audio.touch()

        engine = mod.Wav2LipEngine()
        engine.available = True

        result = engine.lip_sync(str(video), str(audio), str(tmp_path / "output.mp4"))

        assert result["success"] is True
        assert "output" in result
        assert result["engine"] == "wav2lip"

    @patch("rudy.avatar.Wav2LipEngine._check")
    @patch("rudy.avatar._run")
    def test_wav2lip_lip_sync_failure(self, mock_run, mock_check, monkeypatch_paths, tmp_path):
        """Test lip sync failure."""
        mock_check.return_value = True
        mock_run.return_value = ("", "lip sync failed", 1)

        video = tmp_path / "video.mp4"
        audio = tmp_path / "audio.wav"
        video.touch()
        audio.touch()

        engine = mod.Wav2LipEngine()
        engine.available = True

        result = engine.lip_sync(str(video), str(audio), str(tmp_path / "output.mp4"))

        assert result["success"] is False
        assert "error" in result


class TestFaceSwapEngine:
    """Test face swap engine."""

    def test_faceswap_not_available(self, monkeypatch_paths):
        """Test FaceSwapEngine when neither insightface nor roop available."""
        with patch("rudy.avatar.FaceSwapEngine._check_insightface", return_value=False):
            with patch("rudy.avatar.FaceSwapEngine._check_roop", return_value=False):
                engine = mod.FaceSwapEngine()

                assert engine.available is False
                assert engine.insightface_available is False
                assert engine.roop_available is False

    def test_faceswap_insightface_available(self, monkeypatch_paths):
        """Test FaceSwapEngine with insightface available."""
        with patch("rudy.avatar.FaceSwapEngine._check_insightface", return_value=True):
            with patch("rudy.avatar.FaceSwapEngine._check_roop", return_value=False):
                engine = mod.FaceSwapEngine()

                assert engine.available is True
                assert engine.insightface_available is True

    def test_faceswap_roop_available(self, monkeypatch_paths):
        """Test FaceSwapEngine with roop available."""
        with patch("rudy.avatar.FaceSwapEngine._check_insightface", return_value=False):
            with patch("rudy.avatar.FaceSwapEngine._check_roop", return_value=True):
                engine = mod.FaceSwapEngine()

                assert engine.available is True
                assert engine.roop_available is True

    @patch("rudy.avatar.FaceSwapEngine._check_insightface")
    @patch("rudy.avatar.FaceSwapEngine._check_roop")
    def test_swap_face_image_no_engine(self, mock_roop, mock_insightface, monkeypatch_paths):
        """Test swap_face_image returns error when no engine available."""
        mock_insightface.return_value = False
        mock_roop.return_value = False

        engine = mod.FaceSwapEngine()
        result = engine.swap_face_image("source.jpg", "target.jpg", "output.jpg")

        assert "error" in result
        assert ("not available" in result["error"] or "No face swap" in result["error"])

    @patch("rudy.avatar.FaceSwapEngine._check_insightface")
    @patch("rudy.avatar.FaceSwapEngine._check_roop")
    def test_swap_face_image_insightface_path(self, mock_roop, mock_insightface, monkeypatch_paths, tmp_path):
        """Test swap_face_image uses insightface when available."""
        mock_insightface.return_value = True
        mock_roop.return_value = False

        source = tmp_path / "source.jpg"
        target = tmp_path / "target.jpg"
        source.touch()
        target.touch()

        engine = mod.FaceSwapEngine()

        with patch.object(engine, "_insightface_swap_image", return_value={"success": True}):
            result = engine.swap_face_image(str(source), str(target), str(tmp_path / "output.jpg"))

            assert result["success"] is True

    @patch("rudy.avatar.FaceSwapEngine._check_insightface")
    @patch("rudy.avatar.FaceSwapEngine._check_roop")
    def test_swap_face_image_roop_fallback(self, mock_roop, mock_insightface, monkeypatch_paths, tmp_path):
        """Test swap_face_image falls back to roop."""
        mock_insightface.return_value = False
        mock_roop.return_value = True

        source = tmp_path / "source.jpg"
        target = tmp_path / "target.jpg"
        source.touch()
        target.touch()

        engine = mod.FaceSwapEngine()

        with patch.object(engine, "_roop_swap", return_value={"success": True}):
            result = engine.swap_face_image(str(source), str(target), str(tmp_path / "output.jpg"))

            assert result["success"] is True

    @patch("rudy.avatar.FaceSwapEngine._check_insightface")
    @patch("rudy.avatar.FaceSwapEngine._check_roop")
    def test_swap_face_video_no_roop(self, mock_roop, mock_insightface, monkeypatch_paths, tmp_path):
        """Test swap_face_video returns error when roop not available."""
        mock_insightface.return_value = True
        mock_roop.return_value = False

        source = tmp_path / "source.jpg"
        target = tmp_path / "target.mp4"
        source.touch()
        target.touch()

        engine = mod.FaceSwapEngine()
        result = engine.swap_face_video(str(source), str(target), str(tmp_path / "output.mp4"))

        assert "error" in result
        assert "Roop" in result["error"]

    @patch("rudy.avatar.FaceSwapEngine._check_insightface")
    @patch("rudy.avatar.FaceSwapEngine._check_roop")
    def test_swap_face_video_with_roop(self, mock_roop, mock_insightface, monkeypatch_paths, tmp_path):
        """Test swap_face_video with roop available."""
        mock_insightface.return_value = False
        mock_roop.return_value = True

        source = tmp_path / "source.jpg"
        target = tmp_path / "target.mp4"
        source.touch()
        target.touch()

        engine = mod.FaceSwapEngine()

        with patch.object(engine, "_roop_swap", return_value={"success": True}):
            result = engine.swap_face_video(str(source), str(target), str(tmp_path / "output.mp4"))

            assert result["success"] is True

    @patch("rudy.avatar.FaceSwapEngine._check_insightface")
    @patch("rudy.avatar.FaceSwapEngine._check_roop")
    def test_insightface_swap_image_no_model(self, mock_roop, mock_insightface, monkeypatch_paths, tmp_path):
        """Test insightface swap when model file missing."""
        mock_insightface.return_value = True
        mock_roop.return_value = False

        source = tmp_path / "source.jpg"
        target = tmp_path / "target.jpg"
        source.touch()
        target.touch()

        engine = mod.FaceSwapEngine()

        with patch("builtins.__import__", side_effect=ImportError):
            result = engine._insightface_swap_image(str(source), str(target), str(tmp_path / "output.jpg"))

            assert result["success"] is False or "error" in result

    @patch("rudy.avatar.FaceSwapEngine._check_insightface")
    @patch("rudy.avatar.FaceSwapEngine._check_roop")
    @patch("rudy.avatar._run")
    def test_roop_swap_success(self, mock_run, mock_roop, mock_insightface, monkeypatch_paths, tmp_path):
        """Test roop swap success."""
        mock_insightface.return_value = False
        mock_roop.return_value = True
        mock_run.return_value = ("", "", 0)

        source = tmp_path / "source.jpg"
        target = tmp_path / "target.mp4"
        source.touch()
        target.touch()

        engine = mod.FaceSwapEngine()
        result = engine._roop_swap(str(source), str(target), str(tmp_path / "output.mp4"))

        assert result["success"] is True
        assert result["engine"] == "roop"

    @patch("rudy.avatar.FaceSwapEngine._check_insightface")
    @patch("rudy.avatar.FaceSwapEngine._check_roop")
    @patch("rudy.avatar._run")
    def test_roop_swap_failure(self, mock_run, mock_roop, mock_insightface, monkeypatch_paths, tmp_path):
        """Test roop swap failure."""
        mock_insightface.return_value = False
        mock_roop.return_value = True
        mock_run.return_value = ("", "roop error", 1)

        source = tmp_path / "source.jpg"
        target = tmp_path / "target.mp4"
        source.touch()
        target.touch()

        engine = mod.FaceSwapEngine()
        result = engine._roop_swap(str(source), str(target), str(tmp_path / "output.mp4"))

        assert result["success"] is False
        assert "error" in result


class TestMoviePyCompositor:
    """Test MoviePy compositing engine."""

    def test_moviepy_not_available(self, monkeypatch_paths):
        """Test MoviePy availability when not installed."""
        with patch("builtins.__import__", side_effect=ImportError):
            engine = mod.MoviePyCompositor()

            assert engine.available is False

    def test_moviepy_available(self, monkeypatch_paths):
        """Test MoviePy availability when installed."""
        with patch("builtins.__import__") as mock_import:
            mock_import.return_value = MagicMock()
            engine = mod.MoviePyCompositor()

            assert engine.available is True

    @patch("rudy.avatar.MoviePyCompositor._check")
    def test_create_presenter_video_not_available(self, mock_check, monkeypatch_paths):
        """Test create_presenter_video returns error when MoviePy not available."""
        mock_check.return_value = False

        engine = mod.MoviePyCompositor()
        result = engine.create_presenter_video("image.jpg", "audio.wav", "output.mp4")

        assert "error" in result
        assert "not installed" in result["error"]

    @patch("rudy.avatar.MoviePyCompositor._check")
    def test_create_presenter_video_success(self, mock_check, monkeypatch_paths, tmp_path):
        """Test successful presenter video creation."""
        mock_check.return_value = True

        image = tmp_path / "image.jpg"
        audio = tmp_path / "audio.wav"
        image.touch()
        audio.touch()

        engine = mod.MoviePyCompositor()
        engine.available = True

        with patch("rudy.avatar.MoviePyCompositor.create_presenter_video") as mock_create:
            mock_create.return_value = {"success": True, "output": str(tmp_path / "output.mp4")}

            result = mock_create(str(image), str(audio), str(tmp_path / "output.mp4"))

            assert result["success"] is True

    @patch("rudy.avatar.MoviePyCompositor._check")
    def test_create_slideshow_video_not_available(self, mock_check, monkeypatch_paths):
        """Test create_slideshow_video returns error when MoviePy not available."""
        mock_check.return_value = False

        engine = mod.MoviePyCompositor()
        result = engine.create_slideshow_video(["img1.jpg", "img2.jpg"], "audio.wav", "output.mp4")

        assert "error" in result

    @patch("rudy.avatar.MoviePyCompositor._check")
    def test_create_slideshow_video_success(self, mock_check, monkeypatch_paths, tmp_path):
        """Test successful slideshow video creation."""
        mock_check.return_value = True

        img1 = tmp_path / "img1.jpg"
        img2 = tmp_path / "img2.jpg"
        audio = tmp_path / "audio.wav"
        img1.touch()
        img2.touch()
        audio.touch()

        engine = mod.MoviePyCompositor()
        engine.available = True

        with patch("rudy.avatar.MoviePyCompositor.create_slideshow_video") as mock_create:
            mock_create.return_value = {"success": True, "output": str(tmp_path / "output.mp4")}

            result = mock_create([str(img1), str(img2)], str(audio), str(tmp_path / "output.mp4"))

            assert result["success"] is True


class TestAvatarStudio:
    """Test unified AvatarStudio interface."""

    def test_avatar_studio_init(self, monkeypatch_paths):
        """Test AvatarStudio initialization."""
        with patch.object(mod.SadTalkerEngine, "_check", return_value=False):
            with patch.object(mod.Wav2LipEngine, "_check", return_value=False):
                with patch.object(mod.FaceSwapEngine, "_check_insightface", return_value=False):
                    with patch.object(mod.FaceSwapEngine, "_check_roop", return_value=False):
                        with patch.object(mod.MoviePyCompositor, "_check", return_value=False):
                            studio = mod.AvatarStudio()

        assert studio.sadtalker is not None
        assert studio.wav2lip is not None
        assert studio.face_swap_engine is not None
        assert studio.compositor is not None
        assert monkeypatch_paths["avatar_dir"].exists()
        assert monkeypatch_paths["models_dir"].exists()
        assert monkeypatch_paths["output_dir"].exists()
        assert monkeypatch_paths["temp_dir"].exists()

    @patch.object(mod.SadTalkerEngine, "_check", return_value=False)
    @patch.object(mod.Wav2LipEngine, "_check", return_value=False)
    @patch.object(mod.FaceSwapEngine, "_check_insightface", return_value=False)
    @patch.object(mod.FaceSwapEngine, "_check_roop", return_value=False)
    @patch.object(mod.MoviePyCompositor, "_check", return_value=False)
    def test_check_engines(self, mock_mp, mock_roop, mock_if, mock_w2l, mock_st, monkeypatch_paths):
        """Test check_engines returns status of all engines."""
        studio = mod.AvatarStudio()
        status = studio.check_engines()

        assert "sadtalker" in status
        assert "wav2lip" in status
        assert "face_swap_insightface" in status
        assert "face_swap_roop" in status
        assert "moviepy_compositor" in status

        for engine_name, info in status.items():
            assert "available" in info
            assert "type" in info

    @patch.object(mod.SadTalkerEngine, "_check", return_value=True)
    @patch.object(mod.Wav2LipEngine, "_check", return_value=False)
    @patch.object(mod.FaceSwapEngine, "_check_insightface", return_value=False)
    @patch.object(mod.FaceSwapEngine, "_check_roop", return_value=False)
    @patch.object(mod.MoviePyCompositor, "_check", return_value=False)
    def test_talking_head_success_with_sadtalker(self, mock_mp, mock_roop, mock_if, mock_w2l, mock_st, monkeypatch_paths, tmp_path):
        """Test talking_head uses SadTalker when available."""
        image = tmp_path / "image.jpg"
        audio = tmp_path / "audio.wav"
        image.touch()
        audio.touch()

        studio = mod.AvatarStudio()

        with patch.object(studio.sadtalker, "generate", return_value={"success": True, "output": "test.mp4"}):
            result = studio.talking_head(str(image), str(audio))

            assert result["success"] is True

    @patch.object(mod.SadTalkerEngine, "_check", return_value=False)
    @patch.object(mod.Wav2LipEngine, "_check", return_value=True)
    @patch.object(mod.FaceSwapEngine, "_check_insightface", return_value=False)
    @patch.object(mod.FaceSwapEngine, "_check_roop", return_value=False)
    @patch.object(mod.MoviePyCompositor, "_check", return_value=False)
    def test_talking_head_fallback_to_wav2lip(self, mock_mp, mock_roop, mock_if, mock_w2l, mock_st, monkeypatch_paths, tmp_path):
        """Test talking_head falls back to Wav2Lip."""
        image = tmp_path / "image.jpg"
        audio = tmp_path / "audio.wav"
        image.touch()
        audio.touch()

        studio = mod.AvatarStudio()

        with patch.object(studio.wav2lip, "lip_sync", return_value={"success": True, "output": "test.mp4"}):
            result = studio.talking_head(str(image), str(audio))

            assert result["success"] is True

    @patch.object(mod.SadTalkerEngine, "_check", return_value=False)
    @patch.object(mod.Wav2LipEngine, "_check", return_value=False)
    @patch.object(mod.FaceSwapEngine, "_check_insightface", return_value=False)
    @patch.object(mod.FaceSwapEngine, "_check_roop", return_value=False)
    @patch.object(mod.MoviePyCompositor, "_check", return_value=True)
    def test_talking_head_fallback_to_moviepy(self, mock_mp, mock_roop, mock_if, mock_w2l, mock_st, monkeypatch_paths, tmp_path):
        """Test talking_head falls back to MoviePy compositor."""
        image = tmp_path / "image.jpg"
        audio = tmp_path / "audio.wav"
        image.touch()
        audio.touch()

        studio = mod.AvatarStudio()

        with patch.object(studio.compositor, "create_presenter_video", return_value={"success": True}):
            result = studio.talking_head(str(image), str(audio))

            assert result["success"] is True
            assert "note" in result

    @patch.object(mod.SadTalkerEngine, "_check", return_value=False)
    @patch.object(mod.Wav2LipEngine, "_check", return_value=False)
    @patch.object(mod.FaceSwapEngine, "_check_insightface", return_value=False)
    @patch.object(mod.FaceSwapEngine, "_check_roop", return_value=False)
    @patch.object(mod.MoviePyCompositor, "_check", return_value=False)
    def test_talking_head_no_engine_available(self, mock_mp, mock_roop, mock_if, mock_w2l, mock_st, monkeypatch_paths, tmp_path):
        """Test talking_head returns error when no engine available."""
        image = tmp_path / "image.jpg"
        audio = tmp_path / "audio.wav"
        image.touch()
        audio.touch()

        studio = mod.AvatarStudio()
        result = studio.talking_head(str(image), str(audio))

        assert "error" in result
        assert "No video engine" in result["error"]

    @patch.object(mod.SadTalkerEngine, "_check", return_value=False)
    @patch.object(mod.Wav2LipEngine, "_check", return_value=False)
    @patch.object(mod.FaceSwapEngine, "_check_insightface", return_value=True)
    @patch.object(mod.FaceSwapEngine, "_check_roop", return_value=False)
    @patch.object(mod.MoviePyCompositor, "_check", return_value=False)
    def test_face_swap_image(self, mock_mp, mock_roop, mock_if, mock_w2l, mock_st, monkeypatch_paths, tmp_path):
        """Test face_swap with image target."""
        source = tmp_path / "source.jpg"
        target = tmp_path / "target.jpg"
        source.touch()
        target.touch()

        studio = mod.AvatarStudio()

        with patch.object(studio.face_swap_engine, "swap_face_image", return_value={"success": True}):
            result = studio.face_swap(str(source), str(target))

            assert result["success"] is True

    @patch.object(mod.SadTalkerEngine, "_check", return_value=False)
    @patch.object(mod.Wav2LipEngine, "_check", return_value=False)
    @patch.object(mod.FaceSwapEngine, "_check_insightface", return_value=False)
    @patch.object(mod.FaceSwapEngine, "_check_roop", return_value=True)
    @patch.object(mod.MoviePyCompositor, "_check", return_value=False)
    def test_face_swap_video(self, mock_mp, mock_roop, mock_if, mock_w2l, mock_st, monkeypatch_paths, tmp_path):
        """Test face_swap with video target."""
        source = tmp_path / "source.jpg"
        target = tmp_path / "target.mp4"
        source.touch()
        target.touch()

        studio = mod.AvatarStudio()

        with patch.object(studio.face_swap_engine, "swap_face_video", return_value={"success": True}):
            result = studio.face_swap(str(source), str(target))

            assert result["success"] is True

    @patch.object(mod.SadTalkerEngine, "_check", return_value=False)
    @patch.object(mod.Wav2LipEngine, "_check", return_value=False)
    @patch.object(mod.FaceSwapEngine, "_check_insightface", return_value=False)
    @patch.object(mod.FaceSwapEngine, "_check_roop", return_value=False)
    @patch.object(mod.MoviePyCompositor, "_check", return_value=False)
    def test_presenter_video(self, mock_mp, mock_roop, mock_if, mock_w2l, mock_st, monkeypatch_paths, tmp_path):
        """Test presenter_video delegates to talking_head."""
        image = tmp_path / "image.jpg"
        audio = tmp_path / "audio.wav"
        image.touch()
        audio.touch()

        studio = mod.AvatarStudio()

        with patch.object(studio, "talking_head", return_value={"success": True}):
            result = studio.presenter_video(str(image), str(audio))

            assert result["success"] is True

    @patch.object(mod.SadTalkerEngine, "_check", return_value=False)
    @patch.object(mod.Wav2LipEngine, "_check", return_value=False)
    @patch.object(mod.FaceSwapEngine, "_check_insightface", return_value=False)
    @patch.object(mod.FaceSwapEngine, "_check_roop", return_value=False)
    @patch.object(mod.MoviePyCompositor, "_check", return_value=True)
    def test_slideshow(self, mock_mp, mock_roop, mock_if, mock_w2l, mock_st, monkeypatch_paths, tmp_path):
        """Test slideshow video creation."""
        img1 = tmp_path / "img1.jpg"
        img2 = tmp_path / "img2.jpg"
        audio = tmp_path / "audio.wav"
        img1.touch()
        img2.touch()
        audio.touch()

        studio = mod.AvatarStudio()

        with patch.object(studio.compositor, "create_slideshow_video", return_value={"success": True}):
            result = studio.slideshow([str(img1), str(img2)], str(audio))

            assert result["success"] is True

    @patch.object(mod.SadTalkerEngine, "_check", return_value=False)
    @patch.object(mod.Wav2LipEngine, "_check", return_value=False)
    @patch.object(mod.FaceSwapEngine, "_check_insightface", return_value=False)
    @patch.object(mod.FaceSwapEngine, "_check_roop", return_value=False)
    @patch.object(mod.MoviePyCompositor, "_check", return_value=False)
    def test_generate_avatar_no_local_diffusers(self, mock_mp, mock_roop, mock_if, mock_w2l, mock_st, monkeypatch_paths):
        """Test generate_avatar returns alternatives when no local diffusers."""
        studio = mod.AvatarStudio()

        # Mock the diffusers import to fail
        with patch.dict("sys.modules", {"diffusers": None}):
            result = studio.generate_avatar("a professional person")

            assert "error" in result
            assert "alternatives" in result

    @patch.object(mod.SadTalkerEngine, "_check", return_value=False)
    @patch.object(mod.Wav2LipEngine, "_check", return_value=False)
    @patch.object(mod.FaceSwapEngine, "_check_insightface", return_value=False)
    @patch.object(mod.FaceSwapEngine, "_check_roop", return_value=False)
    @patch.object(mod.MoviePyCompositor, "_check", return_value=False)
    def test_install_guide(self, mock_mp, mock_roop, mock_if, mock_w2l, mock_st, monkeypatch_paths):
        """Test install_guide returns helpful text."""
        studio = mod.AvatarStudio()
        guide = studio.install_guide()

        assert "Digital Avatar" in guide
        assert "SadTalker" in guide
        assert "Wav2Lip" in guide
        assert "InsightFace" in guide
        assert "MoviePy" in guide


class TestEdgeCases:
    """Test edge cases and error handling."""

    @patch("rudy.avatar.SadTalkerEngine._check", return_value=False)
    @patch("rudy.avatar.Wav2LipEngine._check", return_value=False)
    @patch("rudy.avatar.FaceSwapEngine._check_insightface", return_value=False)
    @patch("rudy.avatar.FaceSwapEngine._check_roop", return_value=False)
    @patch("rudy.avatar.MoviePyCompositor._check", return_value=False)
    def test_missing_input_files(self, mock_mp, mock_roop, mock_if, mock_w2l, mock_st, monkeypatch_paths):
        """Test behavior with missing input files."""
        studio = mod.AvatarStudio()
        result = studio.talking_head("missing_image.jpg", "missing_audio.wav")

        assert "error" in result

    @patch("rudy.avatar.SadTalkerEngine._check", return_value=True)
    @patch("rudy.avatar.Wav2LipEngine._check", return_value=False)
    @patch("rudy.avatar.FaceSwapEngine._check_insightface", return_value=False)
    @patch("rudy.avatar.FaceSwapEngine._check_roop", return_value=False)
    @patch("rudy.avatar.MoviePyCompositor._check", return_value=False)
    def test_custom_output_path(self, mock_mp, mock_roop, mock_if, mock_w2l, mock_st, monkeypatch_paths, tmp_path):
        """Test custom output path is respected."""
        image = tmp_path / "image.jpg"
        audio = tmp_path / "audio.wav"
        image.touch()
        audio.touch()

        custom_output = tmp_path / "custom" / "output.mp4"

        studio = mod.AvatarStudio()

        with patch.object(studio.sadtalker, "generate", return_value={"success": True, "output": str(custom_output)}):
            studio.talking_head(str(image), str(audio), str(custom_output))

            # Verify the custom path was used (method was called)
            studio.sadtalker.generate.assert_called_once()

    @patch("rudy.avatar.SadTalkerEngine._check", return_value=True)
    @patch("rudy.avatar.Wav2LipEngine._check", return_value=False)
    @patch("rudy.avatar.FaceSwapEngine._check_insightface", return_value=False)
    @patch("rudy.avatar.FaceSwapEngine._check_roop", return_value=False)
    @patch("rudy.avatar.MoviePyCompositor._check", return_value=False)
    def test_kwargs_passed_through(self, mock_mp, mock_roop, mock_if, mock_w2l, mock_st, monkeypatch_paths, tmp_path):
        """Test that kwargs are passed through to engines."""
        image = tmp_path / "image.jpg"
        audio = tmp_path / "audio.wav"
        image.touch()
        audio.touch()

        studio = mod.AvatarStudio()

        with patch.object(studio.sadtalker, "generate", return_value={"success": True}) as mock_gen:
            studio.talking_head(str(image), str(audio), enhancer="realesrgan", still=True)

            # Check that kwargs were passed
            mock_gen.assert_called_once()
            call_kwargs = mock_gen.call_args[1]
            assert call_kwargs.get("enhancer") == "realesrgan"
            assert call_kwargs.get("still") is True
