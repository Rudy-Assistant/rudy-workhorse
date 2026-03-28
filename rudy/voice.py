"""
Voice & Audio Module — Text-to-speech, speech-to-text, audio processing.

Capabilities:
  - TTS: Generate spoken audio from text (gTTS online, pyttsx3 offline)
  - STT: Transcribe audio files to text (OpenAI Whisper, local)
  - Audio processing: Convert formats, trim, merge, adjust volume
  - Podcast/meeting transcription: Process long audio files
  - Voice alerts: Generate spoken alerts for family safety
"""

import json
import logging
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List

log = logging.getLogger(__name__)

DESKTOP = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
AUDIO_DIR = DESKTOP / "rudy-data" / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


class TextToSpeech:
    """Generate spoken audio from text."""

    def speak_online(self, text: str, output_path: str = None,
                     lang: str = "en", slow: bool = False) -> str:
        """Generate speech using Google TTS (requires internet)."""
        try:
            from gtts import gTTS
            if output_path is None:
                output_path = str(AUDIO_DIR / f"tts-{int(time.time())}.mp3")
            tts = gTTS(text=text, lang=lang, slow=slow)
            tts.save(output_path)
            return output_path
        except ImportError:
            raise RuntimeError("gTTS not installed. Run: pip install gtts")

    def speak_offline(self, text: str, output_path: str = None,
                      rate: int = 150, voice_id: int = 0) -> str:
        """Generate speech using pyttsx3 (offline, Windows SAPI5)."""
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", rate)
            voices = engine.getProperty("voices")
            if voice_id < len(voices):
                engine.setProperty("voice", voices[voice_id].id)
            if output_path is None:
                output_path = str(AUDIO_DIR / f"tts-offline-{int(time.time())}.wav")
            engine.save_to_file(text, output_path)
            engine.runAndWait()
            return output_path
        except ImportError:
            raise RuntimeError("pyttsx3 not installed. Run: pip install pyttsx3")

    def speak(self, text: str, output_path: str = None, prefer_offline: bool = False) -> str:
        """Smart TTS — tries online first, falls back to offline."""
        if prefer_offline:
            try:
                return self.speak_offline(text, output_path)
            except Exception as e:
                log.debug(f"Offline TTS failed, falling back to online: {e}")
                return self.speak_online(text, output_path)
        else:
            try:
                return self.speak_online(text, output_path)
            except Exception as e:
                log.debug(f"Online TTS failed, falling back to offline: {e}")
                return self.speak_offline(text, output_path)


class SpeechToText:
    """Transcribe audio to text using OpenAI Whisper (local)."""

    def __init__(self, model_size: str = "base"):
        """
        model_size: tiny, base, small, medium, large
        Smaller = faster + less VRAM, larger = more accurate.
        For CPU-only (AM06 Pro): 'base' is the sweet spot.
        """
        self.model_size = model_size
        self._model = None

    def _load_model(self):
        if self._model is None:
            try:
                import whisper
                self._model = whisper.load_model(self.model_size)
            except ImportError:
                raise RuntimeError("openai-whisper not installed. Run: pip install openai-whisper")
        return self._model

    def transcribe(self, audio_path: str, language: str = "en") -> dict:
        """
        Transcribe an audio file.
        Returns: {"text": str, "segments": [...], "language": str}
        """
        model = self._load_model()
        result = model.transcribe(audio_path, language=language)
        return {
            "text": result["text"],
            "segments": [
                {
                    "start": seg["start"],
                    "end": seg["end"],
                    "text": seg["text"],
                }
                for seg in result.get("segments", [])
            ],
            "language": result.get("language", language),
            "audio_file": audio_path,
        }

    def transcribe_with_timestamps(self, audio_path: str) -> str:
        """Transcribe with human-readable timestamps."""
        result = self.transcribe(audio_path)
        lines = []
        for seg in result["segments"]:
            start = self._format_time(seg["start"])
            end = self._format_time(seg["end"])
            lines.append(f"[{start} → {end}] {seg['text'].strip()}")
        return "\n".join(lines)

    def _format_time(self, seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class AudioProcessor:
    """Audio file processing utilities."""

    def convert(self, input_path: str, output_path: str,
                sample_rate: int = None) -> str:
        """Convert audio between formats."""
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(input_path)
            if sample_rate:
                audio = audio.set_frame_rate(sample_rate)
            audio.export(output_path, format=Path(output_path).suffix.lstrip("."))
            return output_path
        except ImportError:
            raise RuntimeError("pydub not installed. Run: pip install pydub")

    def trim(self, input_path: str, start_ms: int, end_ms: int,
             output_path: str = None) -> str:
        """Trim audio to a specific range."""
        from pydub import AudioSegment
        audio = AudioSegment.from_file(input_path)
        trimmed = audio[start_ms:end_ms]
        if output_path is None:
            output_path = str(AUDIO_DIR / f"trimmed-{int(time.time())}.mp3")
        trimmed.export(output_path)
        return output_path

    def merge(self, file_paths: List[str], output_path: str = None,
              crossfade_ms: int = 100) -> str:
        """Merge multiple audio files."""
        from pydub import AudioSegment
        combined = AudioSegment.empty()
        for fp in file_paths:
            segment = AudioSegment.from_file(fp)
            if len(combined) > 0 and crossfade_ms > 0:
                combined = combined.append(segment, crossfade=crossfade_ms)
            else:
                combined += segment
        if output_path is None:
            output_path = str(AUDIO_DIR / f"merged-{int(time.time())}.mp3")
        combined.export(output_path)
        return output_path

    def adjust_volume(self, input_path: str, db_change: float,
                      output_path: str = None) -> str:
        """Adjust audio volume by dB."""
        from pydub import AudioSegment
        audio = AudioSegment.from_file(input_path)
        adjusted = audio + db_change
        if output_path is None:
            output_path = str(AUDIO_DIR / f"adjusted-{int(time.time())}.mp3")
        adjusted.export(output_path)
        return output_path

    def get_info(self, audio_path: str) -> dict:
        """Get audio file metadata."""
        from pydub import AudioSegment
        audio = AudioSegment.from_file(audio_path)
        return {
            "duration_seconds": len(audio) / 1000.0,
            "channels": audio.channels,
            "sample_rate": audio.frame_rate,
            "sample_width": audio.sample_width,
            "frame_count": audio.frame_count(),
            "file_size_mb": os.path.getsize(audio_path) / (1024 * 1024),
        }

    def download_audio(self, url: str, output_path: str = None) -> str:
        """Download audio/video from URL using yt-dlp."""
        if output_path is None:
            output_path = str(AUDIO_DIR / f"download-{int(time.time())}.mp3")
        try:
            cmd = [
                "yt-dlp", "-x", "--audio-format", "mp3",
                "-o", output_path, url,
            ]
            subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            return output_path
        except FileNotFoundError:
            # Try via Python module
            cmd = ["python", "-m", "yt_dlp", "-x", "--audio-format", "mp3",
                   "-o", output_path, url]
            subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            return output_path


class VoiceModule:
    """Unified voice/audio interface."""

    def __init__(self):
        self.tts = TextToSpeech()
        self.stt = SpeechToText()
        self.processor = AudioProcessor()

    def text_to_audio(self, text: str, **kwargs) -> str:
        return self.tts.speak(text, **kwargs)

    def audio_to_text(self, audio_path: str, **kwargs) -> dict:
        return self.stt.transcribe(audio_path, **kwargs)

    def voice_alert(self, message: str, save: bool = True) -> str:
        """Generate a voice alert (for family safety, notifications)."""
        path = self.tts.speak(message, prefer_offline=True)
        if save:
            alert_path = AUDIO_DIR / f"alert-{int(time.time())}.mp3"
            os.rename(path, str(alert_path))
            return str(alert_path)
        return path


if __name__ == "__main__":
    print("Voice & Audio Module")
    print(f"  Audio directory: {AUDIO_DIR}")
    print("  Available components:")
    for comp, pkg in [("TTS Online", "gtts"), ("TTS Offline", "pyttsx3"),
                       ("STT", "openai-whisper"), ("Audio Processing", "pydub")]:
        try:
            __import__(pkg.replace("-", "_").split("-")[0] if "-" not in pkg else pkg.replace("-",""))
            status = "OK"
        except ImportError:
            status = "NOT INSTALLED"
        print(f"    {comp:20s} [{status}]")
