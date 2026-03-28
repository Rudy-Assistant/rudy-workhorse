import pytest
from unittest.mock import patch, MagicMock, call
from pathlib import Path
import json
import time
import os
import sys

import rudy.voice as mod

# Mock external libraries that might not be installed
sys.modules["gtts"] = MagicMock()
sys.modules["pyttsx3"] = MagicMock()
sys.modules["whisper"] = MagicMock()
sys.modules["pydub"] = MagicMock()
sys.modules["pydub.AudioSegment"] = MagicMock()


@pytest.fixture
def mock_audio_dir(tmp_path, monkeypatch):
    """Redirect AUDIO_DIR to temp directory."""
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mod, "AUDIO_DIR", audio_dir)
    return audio_dir


class TestTextToSpeech:
    """Tests for TextToSpeech class."""

    def test_speak_online_success(self, mock_audio_dir):
        """Test successful online TTS with gTTS."""
        with patch("gtts.gTTS") as mock_gtts_class:
            mock_instance = MagicMock()
            mock_gtts_class.return_value = mock_instance

            tts = mod.TextToSpeech()
            result = tts.speak_online("Hello world", lang="en")

            assert mock_gtts_class.called
            assert mock_instance.save.called
            assert result.endswith(".mp3")
            assert "tts-" in result

    def test_speak_online_with_custom_path(self):
        """Test online TTS with custom output path."""
        with patch("gtts.gTTS") as mock_gtts_class:
            mock_instance = MagicMock()
            mock_gtts_class.return_value = mock_instance
            custom_path = "/tmp/custom_tts.mp3"

            tts = mod.TextToSpeech()
            result = tts.speak_online("Test", output_path=custom_path)

            mock_instance.save.assert_called_once_with(custom_path)
            assert result == custom_path

    def test_speak_online_import_error(self):
        """Test online TTS raises RuntimeError when gTTS not installed."""
        with patch("builtins.__import__", side_effect=ImportError("gTTS")):
            tts = mod.TextToSpeech()
            with pytest.raises(RuntimeError, match="gTTS not installed"):
                tts.speak_online("Hello")

    def test_speak_offline_success(self, mock_audio_dir):
        """Test successful offline TTS with pyttsx3."""
        with patch("pyttsx3.init") as mock_init:
            mock_engine = MagicMock()
            mock_init.return_value = mock_engine
            mock_voice = MagicMock()
            mock_voice.id = "voice_1"
            mock_engine.getProperty.side_effect = lambda x: (
                [mock_voice] if x == "voices" else None
            )

            tts = mod.TextToSpeech()
            result = tts.speak_offline("Hello world", rate=150)

            mock_engine.setProperty.assert_any_call("rate", 150)
            mock_engine.save_to_file.assert_called_once()
            mock_engine.runAndWait.assert_called_once()
            assert result.endswith(".wav")
            assert "tts-offline-" in result

    def test_speak_offline_custom_voice(self):
        """Test offline TTS with custom voice selection."""
        with patch("pyttsx3.init") as mock_init:
            mock_engine = MagicMock()
            mock_init.return_value = mock_engine
            voices = [MagicMock(id=f"voice_{i}") for i in range(3)]
            mock_engine.getProperty.side_effect = lambda x: (
                voices if x == "voices" else None
            )

            tts = mod.TextToSpeech()
            tts.speak_offline("Test", voice_id=2)

            mock_engine.setProperty.assert_any_call("voice", "voice_2")

    def test_speak_offline_voice_id_out_of_range(self):
        """Test offline TTS when voice_id exceeds available voices."""
        with patch("pyttsx3.init") as mock_init:
            mock_engine = MagicMock()
            mock_init.return_value = mock_engine
            voices = [MagicMock(id="voice_0")]
            mock_engine.getProperty.side_effect = lambda x: (
                voices if x == "voices" else None
            )

            tts = mod.TextToSpeech()
            tts.speak_offline("Test", voice_id=5)

            # Should not set voice property if id out of range
            voice_calls = [c for c in mock_engine.setProperty.call_args_list
                          if c[0][0] == "voice"]
            assert len(voice_calls) == 0

    def test_speak_offline_import_error(self):
        """Test offline TTS raises RuntimeError when pyttsx3 not installed."""
        with patch("builtins.__import__", side_effect=ImportError("pyttsx3")):
            tts = mod.TextToSpeech()
            with pytest.raises(RuntimeError, match="pyttsx3 not installed"):
                tts.speak_offline("Hello")

    def test_speak_prefer_offline_success(self, mock_audio_dir):
        """Test smart speak with prefer_offline=True succeeds."""
        with patch.object(mod.TextToSpeech, "speak_offline") as mock_offline:
            mock_offline.return_value = "/tmp/offline.wav"

            tts = mod.TextToSpeech()
            result = tts.speak("Test", prefer_offline=True)

            mock_offline.assert_called_once()
            assert result == "/tmp/offline.wav"

    def test_speak_prefer_offline_fallback_to_online(self, mock_audio_dir):
        """Test smart speak falls back from offline to online."""
        with patch.object(mod.TextToSpeech, "speak_offline") as mock_offline, \
             patch.object(mod.TextToSpeech, "speak_online") as mock_online:
            mock_offline.side_effect = RuntimeError("pyttsx3 failed")
            mock_online.return_value = "/tmp/online.mp3"

            tts = mod.TextToSpeech()
            result = tts.speak("Test", prefer_offline=True)

            mock_offline.assert_called_once()
            mock_online.assert_called_once()
            assert result == "/tmp/online.mp3"

    def test_speak_prefer_online_success(self, mock_audio_dir):
        """Test smart speak with prefer_offline=False succeeds."""
        with patch.object(mod.TextToSpeech, "speak_online") as mock_online:
            mock_online.return_value = "/tmp/online.mp3"

            tts = mod.TextToSpeech()
            result = tts.speak("Test", prefer_offline=False)

            mock_online.assert_called_once()
            assert result == "/tmp/online.mp3"

    def test_speak_prefer_online_fallback_to_offline(self, mock_audio_dir):
        """Test smart speak falls back from online to offline."""
        with patch.object(mod.TextToSpeech, "speak_online") as mock_online, \
             patch.object(mod.TextToSpeech, "speak_offline") as mock_offline:
            mock_online.side_effect = RuntimeError("gTTS failed")
            mock_offline.return_value = "/tmp/offline.wav"

            tts = mod.TextToSpeech()
            result = tts.speak("Test", prefer_offline=False)

            mock_online.assert_called_once()
            mock_offline.assert_called_once()
            assert result == "/tmp/offline.wav"


class TestSpeechToText:
    """Tests for SpeechToText class."""

    def test_init_default_model(self):
        """Test initialization with default model size."""
        stt = mod.SpeechToText()
        assert stt.model_size == "base"
        assert stt._model is None

    def test_init_custom_model(self):
        """Test initialization with custom model size."""
        stt = mod.SpeechToText(model_size="small")
        assert stt.model_size == "small"

    def test_load_model_success(self):
        """Test successful model loading."""
        with patch("whisper.load_model") as mock_load_model:
            mock_model = MagicMock()
            mock_load_model.return_value = mock_model

            stt = mod.SpeechToText(model_size="base")
            model = stt._load_model()

            mock_load_model.assert_called_once_with("base")
            assert model is mock_model
            assert stt._model is mock_model

    def test_load_model_caches(self):
        """Test that model is cached after first load."""
        with patch("whisper.load_model") as mock_load_model:
            mock_model = MagicMock()
            mock_load_model.return_value = mock_model

            stt = mod.SpeechToText()
            stt._load_model()
            stt._load_model()

            # Should only call load_model once due to caching
            mock_load_model.assert_called_once()

    def test_load_model_import_error(self):
        """Test load_model raises RuntimeError when whisper not installed."""
        with patch.dict(sys.modules, {"whisper": None}):
            stt = mod.SpeechToText()
            with pytest.raises(RuntimeError, match="openai-whisper not installed"):
                stt._load_model()

    def test_transcribe_success(self):
        """Test successful transcription."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "text": "Hello world",
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "Hello"},
                {"start": 1.0, "end": 2.0, "text": "world"},
            ],
            "language": "en",
        }

        with patch.object(mod.SpeechToText, "_load_model") as mock_load:
            mock_load.return_value = mock_model

            stt = mod.SpeechToText()
            result = stt.transcribe("audio.wav", language="en")

            assert result["text"] == "Hello world"
            assert len(result["segments"]) == 2
            assert result["language"] == "en"
            assert result["audio_file"] == "audio.wav"
            assert result["segments"][0]["start"] == 0.0

    def test_transcribe_missing_language(self):
        """Test transcription when language not in result."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "text": "Hello",
            "segments": [],
            # No "language" key
        }

        with patch.object(mod.SpeechToText, "_load_model") as mock_load:
            mock_load.return_value = mock_model

            stt = mod.SpeechToText()
            result = stt.transcribe("audio.wav", language="en")

            assert result["language"] == "en"  # Falls back to requested language

    def test_transcribe_with_timestamps_single_segment(self):
        """Test transcription with human-readable timestamps."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "text": "Hello world",
            "segments": [
                {"start": 0.5, "end": 5.75, "text": "Hello world"},
            ],
            "language": "en",
        }

        with patch.object(mod.SpeechToText, "_load_model") as mock_load:
            mock_load.return_value = mock_model

            stt = mod.SpeechToText()
            result = stt.transcribe_with_timestamps("audio.wav")

            assert "[00:00 → 00:05]" in result
            assert "Hello world" in result

    def test_transcribe_with_timestamps_multiple_segments(self):
        """Test timestamps with multiple segments."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "text": "Hello world test",
            "segments": [
                {"start": 0.0, "end": 1.5, "text": "Hello"},
                {"start": 1.5, "end": 3.0, "text": "world"},
                {"start": 120.5, "end": 125.75, "text": "test"},
            ],
            "language": "en",
        }

        with patch.object(mod.SpeechToText, "_load_model") as mock_load:
            mock_load.return_value = mock_model

            stt = mod.SpeechToText()
            result = stt.transcribe_with_timestamps("audio.wav")

            lines = result.split("\n")
            assert len(lines) == 3
            assert "[02:00 → 02:05]" in lines[2]  # 120.5 - 125.75 seconds

    def test_format_time_hours_minutes_seconds(self):
        """Test time formatting with hours."""
        stt = mod.SpeechToText()
        formatted = stt._format_time(3665.0)  # 1:01:05
        assert formatted == "01:01:05"

    def test_format_time_minutes_seconds_only(self):
        """Test time formatting without hours."""
        stt = mod.SpeechToText()
        formatted = stt._format_time(65.0)  # 1:05
        assert formatted == "01:05"

    def test_format_time_seconds_only(self):
        """Test time formatting with less than a minute."""
        stt = mod.SpeechToText()
        formatted = stt._format_time(5.0)
        assert formatted == "00:05"


class TestAudioProcessor:
    """Tests for AudioProcessor class."""

    def test_convert_success(self):
        """Test audio format conversion."""
        with patch("pydub.AudioSegment.from_file") as mock_from_file:
            mock_audio = MagicMock()
            mock_from_file.return_value = mock_audio

            processor = mod.AudioProcessor()
            result = processor.convert("input.wav", "output.mp3")

            mock_from_file.assert_called_once_with("input.wav")
            mock_audio.export.assert_called_once_with("output.mp3", format="mp3")
            assert result == "output.mp3"

    def test_convert_with_sample_rate(self):
        """Test audio conversion with sample rate change."""
        with patch("pydub.AudioSegment.from_file") as mock_from_file:
            mock_audio = MagicMock()
            mock_from_file.return_value = mock_audio
            mock_audio.set_frame_rate.return_value = mock_audio

            processor = mod.AudioProcessor()
            processor.convert("input.wav", "output.wav", sample_rate=44100)

            mock_audio.set_frame_rate.assert_called_once_with(44100)

    def test_convert_import_error(self):
        """Test convert raises RuntimeError when pydub not installed."""
        with patch("builtins.__import__", side_effect=ImportError("pydub")):
            processor = mod.AudioProcessor()
            with pytest.raises(RuntimeError, match="pydub not installed"):
                processor.convert("input.wav", "output.mp3")

    def test_trim_success(self, mock_audio_dir):
        """Test audio trimming."""
        with patch("pydub.AudioSegment.from_file") as mock_from_file:
            mock_audio = MagicMock()
            mock_from_file.return_value = mock_audio
            mock_trimmed = MagicMock()
            mock_audio.__getitem__.return_value = mock_trimmed

            processor = mod.AudioProcessor()
            result = processor.trim("input.mp3", 1000, 5000)

            mock_audio.__getitem__.assert_called_once_with(slice(1000, 5000))
            mock_trimmed.export.assert_called_once()
            assert "trimmed-" in result

    def test_trim_custom_output_path(self):
        """Test trim with custom output path."""
        with patch("pydub.AudioSegment.from_file") as mock_from_file:
            mock_audio = MagicMock()
            mock_from_file.return_value = mock_audio
            mock_trimmed = MagicMock()
            mock_audio.__getitem__.return_value = mock_trimmed
            custom_path = "/tmp/custom_trim.mp3"

            processor = mod.AudioProcessor()
            result = processor.trim("input.mp3", 0, 1000, output_path=custom_path)

            assert result == custom_path

    def test_merge_single_file(self, mock_audio_dir):
        """Test merging with a single file."""
        with patch("pydub.AudioSegment.empty") as mock_empty_func, \
             patch("pydub.AudioSegment.from_file") as mock_from_file:
            mock_empty = MagicMock()
            mock_empty_func.return_value = mock_empty
            mock_segment = MagicMock()
            mock_from_file.return_value = mock_segment
            # For single file: len(combined) == 0, so uses += operator (__iadd__)
            mock_empty.__len__.return_value = 0
            mock_empty.__iadd__.return_value = mock_empty

            processor = mod.AudioProcessor()
            result = processor.merge(["file1.mp3"])

            mock_from_file.assert_called_once_with("file1.mp3")
            # Single file goes through else branch using += (i.e., __iadd__)
            mock_empty.__iadd__.assert_called_once_with(mock_segment)
            assert "merged-" in result

    def test_merge_multiple_files_no_crossfade(self, mock_audio_dir):
        """Test merging multiple files without crossfade."""
        with patch("pydub.AudioSegment.empty") as mock_empty_func, \
             patch("pydub.AudioSegment.from_file") as mock_from_file:
            mock_empty = MagicMock()
            mock_empty_func.return_value = mock_empty
            mock_segment1 = MagicMock()
            mock_segment2 = MagicMock()
            mock_from_file.side_effect = [mock_segment1, mock_segment2]
            # First iteration: len == 0 (uses +=), then after that len > 0
            # but crossfade_ms == 0, so still uses += for both (via __iadd__)
            mock_empty.__len__.side_effect = [0, 100]
            mock_empty.__iadd__.return_value = mock_empty

            processor = mod.AudioProcessor()
            processor.merge(["file1.mp3", "file2.mp3"], crossfade_ms=0)

            assert mock_from_file.call_count == 2
            # With crossfade_ms=0, both files use += operator (__iadd__)
            assert mock_empty.__iadd__.call_count == 2

    def test_merge_with_crossfade(self, mock_audio_dir):
        """Test merging multiple files with crossfade."""
        with patch("pydub.AudioSegment.empty") as mock_empty_func, \
             patch("pydub.AudioSegment.from_file") as mock_from_file:
            mock_empty = MagicMock()
            mock_empty_func.return_value = mock_empty
            mock_segment1 = MagicMock()
            mock_segment2 = MagicMock()
            mock_from_file.side_effect = [mock_segment1, mock_segment2]
            # First iteration: len == 0 (uses +=), then len > 0 and crossfade > 0
            # So second file uses append
            mock_empty.__len__.side_effect = [0, 100]
            mock_empty.__iadd__.return_value = mock_empty
            mock_empty.append.return_value = mock_empty

            processor = mod.AudioProcessor()
            processor.merge(["file1.mp3", "file2.mp3"], crossfade_ms=200)

            # First file uses += (due to len == 0), second uses append
            assert mock_empty.__iadd__.call_count == 1
            assert mock_empty.append.call_count == 1

    def test_adjust_volume_increase(self):
        """Test adjusting volume (increase)."""
        with patch("pydub.AudioSegment.from_file") as mock_from_file:
            mock_audio = MagicMock()
            mock_from_file.return_value = mock_audio
            mock_adjusted = MagicMock()
            mock_audio.__add__.return_value = mock_adjusted

            processor = mod.AudioProcessor()
            processor.adjust_volume("input.mp3", db_change=3.0)

            mock_audio.__add__.assert_called_once_with(3.0)
            mock_adjusted.export.assert_called_once()

    def test_adjust_volume_decrease(self, mock_audio_dir):
        """Test adjusting volume (decrease)."""
        with patch("pydub.AudioSegment.from_file") as mock_from_file:
            mock_audio = MagicMock()
            mock_from_file.return_value = mock_audio
            mock_adjusted = MagicMock()
            mock_audio.__add__.return_value = mock_adjusted

            processor = mod.AudioProcessor()
            result = processor.adjust_volume("input.mp3", db_change=-5.0)

            mock_audio.__add__.assert_called_once_with(-5.0)
            assert "adjusted-" in result

    def test_get_info_success(self):
        """Test getting audio file metadata."""
        with patch("pydub.AudioSegment.from_file") as mock_from_file, \
             patch("os.path.getsize") as mock_getsize:
            mock_audio = MagicMock()
            mock_from_file.return_value = mock_audio
            mock_audio.channels = 2
            mock_audio.frame_rate = 44100
            mock_audio.sample_width = 2
            mock_audio.__len__.return_value = 180000  # 180 seconds in ms
            mock_audio.frame_count.return_value = 7938000
            mock_getsize.return_value = 5242880  # 5 MB

            processor = mod.AudioProcessor()
            result = processor.get_info("audio.mp3")

            assert result["duration_seconds"] == 180.0
            assert result["channels"] == 2
            assert result["sample_rate"] == 44100
            assert result["sample_width"] == 2
            assert result["frame_count"] == 7938000
            assert result["file_size_mb"] == 5.0

    def test_download_audio_yt_dlp_success(self, mock_audio_dir):
        """Test successful audio download with yt-dlp."""
        with patch("subprocess.run") as mock_run:
            processor = mod.AudioProcessor()
            result = processor.download_audio("https://example.com/audio.mp3")

            assert mock_run.called
            call_args = mock_run.call_args[0][0]
            assert "yt-dlp" in call_args
            assert "-x" in call_args
            assert "--audio-format" in call_args
            assert "mp3" in call_args
            assert "download-" in result

    def test_download_audio_custom_path(self):
        """Test audio download with custom output path."""
        with patch("subprocess.run") as mock_run:
            custom_path = "/tmp/custom_audio.mp3"
            processor = mod.AudioProcessor()
            result = processor.download_audio("https://example.com/audio.mp3",
                                             output_path=custom_path)

            assert result == custom_path
            call_args = mock_run.call_args[0][0]
            assert custom_path in call_args

    def test_download_audio_fallback_to_python_module(self):
        """Test audio download falls back to python module when yt-dlp not found."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("yt-dlp not found")

            processor = mod.AudioProcessor()

            # This will raise because the fallback also fails
            # (we can't easily mock both calls without more setup)
            # but we can verify the method handles the FileNotFoundError
            with pytest.raises(Exception):
                processor.download_audio("https://example.com/audio.mp3")

            # Should have been called twice (first with yt-dlp, then with python -m)
            assert mock_run.call_count == 2


class TestVoiceModule:
    """Tests for unified VoiceModule class."""

    def test_init(self):
        """Test VoiceModule initialization."""
        voice = mod.VoiceModule()
        assert isinstance(voice.tts, mod.TextToSpeech)
        assert isinstance(voice.stt, mod.SpeechToText)
        assert isinstance(voice.processor, mod.AudioProcessor)

    def test_text_to_audio(self):
        """Test text_to_audio delegates to TTS."""
        with patch.object(mod.TextToSpeech, "speak") as mock_speak:
            mock_speak.return_value = "/tmp/output.mp3"

            voice = mod.VoiceModule()
            result = voice.text_to_audio("Hello world", prefer_offline=True)

            mock_speak.assert_called_once_with("Hello world", prefer_offline=True)
            assert result == "/tmp/output.mp3"

    def test_audio_to_text(self):
        """Test audio_to_text delegates to STT."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "text": "Hello world",
            "segments": [],
            "language": "en",
            "audio_file": "audio.wav",
        }

        with patch.object(mod.SpeechToText, "_load_model") as mock_load:
            mock_load.return_value = mock_model

            voice = mod.VoiceModule()
            result = voice.audio_to_text("audio.wav", language="en")

            assert result["text"] == "Hello world"

    def test_voice_alert_with_save(self, mock_audio_dir):
        """Test voice alert generation with save."""
        alert_file = mock_audio_dir / "alert.wav"
        alert_file.touch()

        with patch.object(mod.TextToSpeech, "speak") as mock_speak, \
             patch("os.rename") as mock_rename:
            mock_speak.return_value = str(alert_file)

            voice = mod.VoiceModule()
            result = voice.voice_alert("Emergency alert", save=True)

            mock_speak.assert_called_once_with("Emergency alert", prefer_offline=True)
            mock_rename.assert_called_once()
            assert "alert-" in result

    def test_voice_alert_without_save(self):
        """Test voice alert generation without saving."""
        with patch.object(mod.TextToSpeech, "speak") as mock_speak:
            mock_speak.return_value = "/tmp/temp_alert.wav"

            voice = mod.VoiceModule()
            result = voice.voice_alert("Quick alert", save=False)

            assert result == "/tmp/temp_alert.wav"
            # Should not call os.rename when save=False


class TestEdgeCases:
    """Edge cases and error handling."""

    def test_empty_text_to_speech(self, mock_audio_dir):
        """Test TTS with empty string."""
        with patch("gtts.gTTS") as mock_gtts_class:
            mock_instance = MagicMock()
            mock_gtts_class.return_value = mock_instance

            tts = mod.TextToSpeech()
            result = tts.speak_online("", lang="en")

            assert mock_instance.save.called
            assert result.endswith(".mp3")

    def test_very_long_text_to_speech(self):
        """Test TTS with very long text."""
        with patch("gtts.gTTS") as mock_gtts_class:
            mock_instance = MagicMock()
            mock_gtts_class.return_value = mock_instance

            long_text = "Hello world " * 10000
            tts = mod.TextToSpeech()
            tts.speak_online(long_text)

            assert mock_gtts_class.called

    def test_transcribe_empty_audio(self):
        """Test transcription with empty segments."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "text": "",
            "segments": [],
            "language": "en",
        }

        with patch.object(mod.SpeechToText, "_load_model") as mock_load:
            mock_load.return_value = mock_model

            stt = mod.SpeechToText()
            result = stt.transcribe("silent.wav")

            assert result["text"] == ""
            assert result["segments"] == []

    def test_transcribe_multiple_languages(self):
        """Test transcription result preserves detected language."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "text": "Bonjour",
            "segments": [{"start": 0.0, "end": 1.0, "text": "Bonjour"}],
            "language": "fr",
        }

        with patch.object(mod.SpeechToText, "_load_model") as mock_load:
            mock_load.return_value = mock_model

            stt = mod.SpeechToText()
            result = stt.transcribe("french_audio.wav", language="en")

            assert result["language"] == "fr"

    def test_merge_empty_list(self, mock_audio_dir):
        """Test merging with empty file list."""
        with patch("pydub.AudioSegment.empty") as mock_empty_func:
            mock_empty = MagicMock()
            mock_empty_func.return_value = mock_empty

            processor = mod.AudioProcessor()
            result = processor.merge([])

            mock_empty_func.assert_called_once()
            assert "merged-" in result

    def test_format_time_zero_seconds(self):
        """Test time formatting with zero."""
        stt = mod.SpeechToText()
        formatted = stt._format_time(0.0)
        assert formatted == "00:00"

    def test_format_time_large_values(self):
        """Test time formatting with large hour values."""
        stt = mod.SpeechToText()
        formatted = stt._format_time(36000.0)  # 10 hours
        assert formatted == "10:00:00"

    def test_audio_processor_nonexistent_file_properties(self):
        """Test get_info with file metadata."""
        with patch("pydub.AudioSegment.from_file") as mock_from_file, \
             patch("os.path.getsize") as mock_getsize:
            mock_audio = MagicMock()
            mock_from_file.return_value = mock_audio
            mock_audio.__len__.return_value = 0
            mock_getsize.return_value = 1024

            processor = mod.AudioProcessor()
            result = processor.get_info("nonexistent.mp3")

            assert result["duration_seconds"] == 0.0
            assert result["file_size_mb"] == pytest.approx(0.0009765625)  # 1024 / (1024*1024)


class TestIntegration:
    """Integration tests combining multiple components."""

    def test_tts_then_stt_workflow(self):
        """Test TTS output can be used as STT input."""
        mock_stt_model = MagicMock()
        mock_stt_model.transcribe.return_value = {
            "text": "Hello world",
            "segments": [],
            "language": "en",
            "audio_file": "tts_output.wav",
        }

        with patch.object(mod.TextToSpeech, "speak_offline") as mock_tts, \
             patch.object(mod.SpeechToText, "_load_model") as mock_stt_load:
            mock_tts.return_value = "tts_output.wav"
            mock_stt_load.return_value = mock_stt_model

            tts = mod.TextToSpeech()
            stt = mod.SpeechToText()

            audio_file = tts.speak_offline("Hello world")
            transcription = stt.transcribe(audio_file)

            assert transcription["audio_file"] == audio_file

    def test_voice_module_complete_workflow(self, mock_audio_dir):
        """Test complete text->audio->text workflow."""
        mock_stt_model = MagicMock()
        mock_stt_model.transcribe.return_value = {
            "text": "Original message",
            "segments": [{"start": 0.0, "end": 1.0, "text": "Original message"}],
            "language": "en",
            "audio_file": "test.wav",
        }

        with patch.object(mod.TextToSpeech, "speak") as mock_speak, \
             patch.object(mod.SpeechToText, "_load_model") as mock_load:
            mock_speak.return_value = "test.wav"
            mock_load.return_value = mock_stt_model

            voice = mod.VoiceModule()
            audio = voice.text_to_audio("Original message")
            transcribed = voice.audio_to_text(audio)

            assert transcribed["text"] == "Original message"

    def test_multiple_model_sizes(self):
        """Test SpeechToText with different model sizes."""
        for size in ["tiny", "base", "small", "medium", "large"]:
            stt = mod.SpeechToText(model_size=size)
            assert stt.model_size == size
