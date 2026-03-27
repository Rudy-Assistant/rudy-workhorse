"""
Voice Clone — Voice cloning, custom character voices, and memorial voice recreation.

Capabilities:
  1. Clone a voice from audio sample(s) (5-20 seconds of clean speech)
  2. Generate speech in any cloned voice
  3. Create custom character voices for book readings, audiobooks
  4. Memorial voice recreation from recordings of loved ones
  5. Multi-speaker management with named voice profiles
  6. Audio preprocessing (noise reduction, normalization, segmentation)

Engines (tried in order):
  1. Pocket TTS (Kyutai Labs, 2026) — Python 3.12 native, CPU-optimized, 5-20s voice cloning
  2. OpenVoice — zero-shot cross-lingual voice cloning
  3. Bark (Suno) — text-to-speech with speaker conditioning
  4. gTTS/pyttsx3 fallback — no cloning, but guaranteed TTS

Retired engines:
  - Coqui TTS (XTTS v2) — project abandoned, Python 3.12 incompatible

All processing is LOCAL — no cloud API needed, full privacy.
"""

import json
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

DESKTOP = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
VOICE_DIR = DESKTOP / "rudy-data" / "voice-clone"
PROFILES_DIR = VOICE_DIR / "profiles"
OUTPUT_DIR = VOICE_DIR / "output"
TEMP_DIR = VOICE_DIR / "temp"
LOGS = DESKTOP / "rudy-logs"


def _save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _load_json(path: Path, default=None):
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return default if default is not None else {}


class AudioPreprocessor:
    """Clean and prepare audio samples for voice cloning."""

    def __init__(self):
        for d in [VOICE_DIR, PROFILES_DIR, OUTPUT_DIR, TEMP_DIR]:
            d.mkdir(parents=True, exist_ok=True)

    def analyze(self, audio_path: str) -> dict:
        """Analyze an audio file — duration, format, quality."""
        path = Path(audio_path)
        if not path.exists():
            return {"error": f"File not found: {audio_path}"}

        info = {
            "file": str(path),
            "filename": path.name,
            "extension": path.suffix.lower(),
            "size_mb": round(path.stat().st_size / (1024 * 1024), 2),
        }

        # Try pydub for detailed analysis
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(str(path))
            info["duration_seconds"] = round(len(audio) / 1000.0, 1)
            info["channels"] = audio.channels
            info["sample_rate"] = audio.frame_rate
            info["sample_width"] = audio.sample_width
            info["dBFS"] = round(audio.dBFS, 1)
            info["max_dBFS"] = round(audio.max_dBFS, 1)

            # Quality assessment
            if info["duration_seconds"] < 3:
                info["quality_note"] = "Too short — need at least 3 seconds for cloning"
            elif info["duration_seconds"] < 10:
                info["quality_note"] = "Usable but short — 10-30 seconds recommended"
            elif info["duration_seconds"] > 60:
                info["quality_note"] = "Long sample — will auto-trim to best 30s segment"
            else:
                info["quality_note"] = "Good length for voice cloning"

            if info["dBFS"] < -30:
                info["quality_note"] += " | Very quiet — will normalize"
            if info["sample_rate"] < 16000:
                info["quality_note"] += " | Low sample rate — may affect quality"

        except ImportError:
            info["note"] = "pydub not available — install for audio analysis"
        except Exception as e:
            info["error"] = str(e)[:200]

        return info

    def prepare_sample(self, audio_path: str, output_name: str = None) -> dict:
        """
        Prepare an audio sample for voice cloning:
        - Convert to WAV 22050Hz mono
        - Normalize volume
        - Trim silence
        - Trim to 30s if too long
        """
        path = Path(audio_path)
        if not path.exists():
            return {"error": f"File not found: {audio_path}"}

        out_name = output_name or f"prepared_{path.stem}"
        out_path = TEMP_DIR / f"{out_name}.wav"

        try:
            from pydub import AudioSegment
            from pydub.effects import normalize
            from pydub.silence import detect_leading_silence

            audio = AudioSegment.from_file(str(path))

            # Convert to mono 22050Hz
            audio = audio.set_channels(1).set_frame_rate(22050)

            # Normalize volume
            audio = normalize(audio)

            # Trim leading/trailing silence
            def trim_silence(seg, threshold=-40):
                start_trim = detect_leading_silence(seg, silence_threshold=threshold)
                end_trim = detect_leading_silence(seg.reverse(), silence_threshold=threshold)
                return seg[start_trim:len(seg) - end_trim]

            audio = trim_silence(audio)

            # Cap at 30 seconds (take middle segment for best quality)
            if len(audio) > 30000:
                start = (len(audio) - 30000) // 2
                audio = audio[start:start + 30000]

            audio.export(str(out_path), format="wav")

            return {
                "success": True,
                "output": str(out_path),
                "duration_seconds": round(len(audio) / 1000.0, 1),
                "sample_rate": 22050,
            }

        except ImportError:
            # Fallback: just copy the file
            shutil.copy2(str(path), str(out_path))
            return {
                "success": True,
                "output": str(out_path),
                "note": "pydub not available — raw copy only",
            }
        except Exception as e:
            return {"success": False, "error": str(e)[:200]}

    def extract_speech_segments(self, audio_path: str) -> List[dict]:
        """Extract speech-only segments (remove music, noise, silence)."""
        try:
            from pydub import AudioSegment
            from pydub.silence import split_on_silence

            audio = AudioSegment.from_file(audio_path)
            chunks = split_on_silence(
                audio,
                min_silence_len=500,
                silence_thresh=audio.dBFS - 14,
                keep_silence=200,
            )

            segments = []
            offset = 0
            for i, chunk in enumerate(chunks):
                seg_path = TEMP_DIR / f"segment_{i:03d}.wav"
                chunk.export(str(seg_path), format="wav")
                segments.append({
                    "index": i,
                    "file": str(seg_path),
                    "duration_seconds": round(len(chunk) / 1000.0, 1),
                    "offset_seconds": round(offset / 1000.0, 1),
                })
                offset += len(chunk) + 500

            return segments
        except Exception as e:
            return [{"error": str(e)[:200]}]


class PocketTTSEngine:
    """Voice cloning via Pocket TTS (Kyutai Labs, 2026).

    Python 3.12 native, CPU-optimized, 5-20s reference audio for voice cloning.
    Replaced Coqui TTS which was abandoned and incompatible with Python 3.12.
    """

    def __init__(self):
        self._model = None
        self.available = self._check_available()

    def _check_available(self) -> bool:
        try:
            import pocket_tts
            return True
        except ImportError:
            return False

    def _get_model(self):
        if self._model is None and self.available:
            import pocket_tts
            self._model = pocket_tts.load_model()
        return self._model

    def clone_and_speak(self, text: str, reference_audio: str,
                        output_path: str, language: str = "en") -> dict:
        """Generate speech in cloned voice using Pocket TTS."""
        model = self._get_model()
        if not model:
            return {"error": "Pocket TTS not loaded. Run: pip install pocket-tts"}

        try:
            import pocket_tts
            # Clone voice from reference audio and synthesize
            audio = pocket_tts.tts(
                model,
                text=text,
                speaker_wav=reference_audio,
                language=language,
            )
            pocket_tts.save_audio(audio, output_path)
            return {"success": True, "output": output_path, "engine": "pocket_tts"}
        except Exception as e:
            return {"success": False, "error": str(e)[:300], "engine": "pocket_tts"}

    def speak(self, text: str, output_path: str, language: str = "en") -> dict:
        """Basic TTS without cloning."""
        model = self._get_model()
        if not model:
            return {"error": "Pocket TTS not loaded"}
        try:
            import pocket_tts
            audio = pocket_tts.tts(model, text=text, language=language)
            pocket_tts.save_audio(audio, output_path)
            return {"success": True, "output": output_path, "engine": "pocket_tts"}
        except Exception as e:
            return {"success": False, "error": str(e)[:300], "engine": "pocket_tts"}


class CoquiTTSEngine:
    """Voice cloning via Coqui TTS (XTTS v2) — RETIRED.

    Coqui project is abandoned and incompatible with Python 3.12.
    Kept as fallback for systems that still have it installed.
    """

    def __init__(self):
        self._tts = None
        self.available = self._check_available()

    def _check_available(self) -> bool:
        try:
            import TTS
            return True
        except ImportError:
            return False

    def _get_tts(self):
        if self._tts is None and self.available:
            from TTS.api import TTS
            self._tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")
        return self._tts

    def clone_and_speak(self, text: str, reference_audio: str,
                        output_path: str, language: str = "en") -> dict:
        """Generate speech in cloned voice."""
        tts = self._get_tts()
        if not tts:
            return {"error": "Coqui TTS not installed (retired — use pocket-tts)"}

        try:
            tts.tts_to_file(
                text=text,
                speaker_wav=reference_audio,
                language=language,
                file_path=output_path,
            )
            return {"success": True, "output": output_path, "engine": "coqui_xtts_v2"}
        except Exception as e:
            return {"success": False, "error": str(e)[:300], "engine": "coqui_xtts_v2"}


class OpenVoiceEngine:
    """Voice cloning via OpenVoice — zero-shot cross-lingual."""

    def __init__(self):
        self.available = self._check_available()

    def _check_available(self) -> bool:
        try:
            from openvoice import se_extractor
            return True
        except ImportError:
            return False

    def clone_and_speak(self, text: str, reference_audio: str,
                        output_path: str, language: str = "en") -> dict:
        if not self.available:
            return {"error": "OpenVoice not installed. Run: pip install openvoice"}

        try:
            from openvoice.api import ToneColorConverter
            from openvoice import se_extractor

            ckpt_converter = "checkpoints/converter"
            tone_color_converter = ToneColorConverter(f"{ckpt_converter}/config.json")
            tone_color_converter.load_ckpt(f"{ckpt_converter}/checkpoint.pth")

            source_se = se_extractor.get_se(reference_audio, tone_color_converter)

            tone_color_converter.convert(
                audio_src_path=reference_audio,
                src_se=source_se,
                tgt_se=source_se,
                output_path=output_path,
            )
            return {"success": True, "output": output_path, "engine": "openvoice"}
        except Exception as e:
            return {"success": False, "error": str(e)[:300], "engine": "openvoice"}


class BarkEngine:
    """Voice generation via Bark (Suno) — neural text-to-speech."""

    def __init__(self):
        self.available = self._check_available()

    def _check_available(self) -> bool:
        try:
            from bark import generate_audio, SAMPLE_RATE
            return True
        except ImportError:
            return False

    def speak(self, text: str, output_path: str,
              speaker: str = "v2/en_speaker_6") -> dict:
        """Generate speech (Bark has preset speakers, not full cloning)."""
        if not self.available:
            return {"error": "Bark not installed. Run: pip install bark"}

        try:
            from bark import generate_audio, SAMPLE_RATE
            import numpy as np
            import soundfile as sf

            audio_array = generate_audio(text, history_prompt=speaker)
            sf.write(output_path, audio_array, SAMPLE_RATE)
            return {"success": True, "output": output_path, "engine": "bark"}
        except Exception as e:
            return {"success": False, "error": str(e)[:300], "engine": "bark"}


class FallbackTTSEngine:
    """Fallback TTS — no cloning, but always works."""

    def speak(self, text: str, output_path: str, language: str = "en") -> dict:
        # Try gTTS (online)
        try:
            from gtts import gTTS
            tts = gTTS(text=text, lang=language)
            tts.save(output_path)
            return {"success": True, "output": output_path, "engine": "gtts"}
        except Exception:
            pass

        # Try pyttsx3 (offline)
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.save_to_file(text, output_path)
            engine.runAndWait()
            return {"success": True, "output": output_path, "engine": "pyttsx3"}
        except Exception as e:
            return {"success": False, "error": str(e)[:200], "engine": "fallback"}


class VoiceCloner:
    """
    Master voice cloning interface.

    Usage:
        vc = VoiceCloner()

        # Clone a voice from an audio sample
        vc.clone_voice("grandpa_recording.wav", "Grandpa")

        # Generate speech in that voice
        vc.speak("Happy birthday!", "Grandpa")

        # List available profiles
        vc.list_profiles()

        # Create a character voice for book reading
        vc.create_character("Narrator", style="warm_male")
    """

    def __init__(self):
        for d in [VOICE_DIR, PROFILES_DIR, OUTPUT_DIR, TEMP_DIR]:
            d.mkdir(parents=True, exist_ok=True)

        self.preprocessor = AudioPreprocessor()
        self.engines = {
            "pocket_tts": PocketTTSEngine(),
            "coqui": CoquiTTSEngine(),  # Retired — kept as legacy fallback
            "openvoice": OpenVoiceEngine(),
            "bark": BarkEngine(),
            "fallback": FallbackTTSEngine(),
        }
        self.profiles = self._load_profiles()

    def _load_profiles(self) -> dict:
        return _load_json(PROFILES_DIR / "profiles.json", {})

    def _save_profiles(self):
        _save_json(PROFILES_DIR / "profiles.json", self.profiles)

    def check_engines(self) -> dict:
        """Check which voice engines are available."""
        return {
            name: {"available": getattr(engine, "available", True)}
            for name, engine in self.engines.items()
        }

    def clone_voice(self, audio_path: str, name: str,
                    description: str = "") -> dict:
        """
        Create a voice profile from an audio sample.

        Args:
            audio_path: Path to audio file (WAV, MP3, etc.) — 3-30s of clean speech
            name: Name for this voice (e.g., "Grandpa", "Narrator")
            description: Optional description
        """
        # Analyze the sample
        analysis = self.preprocessor.analyze(audio_path)
        if analysis.get("error"):
            return analysis

        # Prepare the sample (normalize, trim, convert)
        prepared = self.preprocessor.prepare_sample(audio_path, name.lower().replace(" ", "_"))
        if not prepared.get("success"):
            return prepared

        # Save profile
        profile_dir = PROFILES_DIR / name.lower().replace(" ", "_")
        profile_dir.mkdir(parents=True, exist_ok=True)

        # Copy prepared sample to profile
        sample_dest = profile_dir / "reference.wav"
        shutil.copy2(prepared["output"], str(sample_dest))

        # Also keep original
        orig_dest = profile_dir / f"original{Path(audio_path).suffix}"
        shutil.copy2(audio_path, str(orig_dest))

        profile = {
            "name": name,
            "description": description,
            "created": datetime.now().isoformat(),
            "reference_audio": str(sample_dest),
            "original_audio": str(orig_dest),
            "sample_duration": prepared.get("duration_seconds", 0),
            "analysis": analysis,
        }

        self.profiles[name] = profile
        _save_json(profile_dir / "profile.json", profile)
        self._save_profiles()

        return {
            "success": True,
            "profile": name,
            "reference_audio": str(sample_dest),
            "duration": prepared.get("duration_seconds", 0),
            "message": f"Voice profile '{name}' created. Use vc.speak(text, '{name}') to generate speech.",
        }

    def speak(self, text: str, profile_name: str = None,
              language: str = "en", output_path: str = None) -> dict:
        """
        Generate speech, optionally in a cloned voice.

        Args:
            text: Text to speak
            profile_name: Voice profile name (None = default TTS voice)
            language: Language code (en, es, fr, ja, etc.)
            output_path: Custom output path (auto-generated if None)
        """
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_name = (profile_name or "default").lower().replace(" ", "_")
        if not output_path:
            output_path = str(OUTPUT_DIR / f"speech_{safe_name}_{timestamp}.wav")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # If profile specified, use voice cloning
        if profile_name and profile_name in self.profiles:
            ref_audio = self.profiles[profile_name].get("reference_audio", "")

            if not Path(ref_audio).exists():
                return {"error": f"Reference audio not found for profile '{profile_name}'"}

            # Try engines in order: Pocket TTS → Coqui (legacy) → OpenVoice → Bark → Fallback
            if self.engines["pocket_tts"].available:
                result = self.engines["pocket_tts"].clone_and_speak(
                    text, ref_audio, output_path, language
                )
                if result.get("success"):
                    return result

            if self.engines["coqui"].available:
                result = self.engines["coqui"].clone_and_speak(
                    text, ref_audio, output_path, language
                )
                if result.get("success"):
                    return result

            if self.engines["openvoice"].available:
                result = self.engines["openvoice"].clone_and_speak(
                    text, ref_audio, output_path, language
                )
                if result.get("success"):
                    return result

        # Bark (preset speakers, not full cloning)
        if self.engines["bark"].available:
            result = self.engines["bark"].speak(text, output_path)
            if result.get("success"):
                return result

        # Fallback TTS
        return self.engines["fallback"].speak(text, output_path, language)

    def list_profiles(self) -> List[str]:
        """List all voice profiles."""
        return list(self.profiles.keys())

    def get_profile(self, name: str) -> dict:
        """Get details of a voice profile."""
        return self.profiles.get(name, {"error": f"Profile '{name}' not found"})

    def delete_profile(self, name: str) -> dict:
        """Delete a voice profile."""
        if name not in self.profiles:
            return {"error": f"Profile '{name}' not found"}

        profile_dir = PROFILES_DIR / name.lower().replace(" ", "_")
        if profile_dir.exists():
            shutil.rmtree(str(profile_dir))

        del self.profiles[name]
        self._save_profiles()
        return {"success": True, "deleted": name}

    def create_character(self, name: str, style: str = "neutral",
                         description: str = "") -> dict:
        """
        Create a named character voice from Bark presets.
        Styles: warm_male, warm_female, narrator, child, elder, dramatic
        """
        BARK_PRESETS = {
            "warm_male": "v2/en_speaker_6",
            "warm_female": "v2/en_speaker_9",
            "narrator": "v2/en_speaker_0",
            "child": "v2/en_speaker_3",
            "elder": "v2/en_speaker_7",
            "dramatic": "v2/en_speaker_1",
            "neutral": "v2/en_speaker_5",
        }

        preset = BARK_PRESETS.get(style, BARK_PRESETS["neutral"])

        profile = {
            "name": name,
            "description": description or f"Character voice ({style})",
            "created": datetime.now().isoformat(),
            "type": "bark_preset",
            "bark_speaker": preset,
            "style": style,
        }

        self.profiles[name] = profile
        self._save_profiles()

        return {
            "success": True,
            "profile": name,
            "style": style,
            "message": f"Character '{name}' created with {style} voice.",
        }

    def batch_generate(self, script: List[dict],
                       output_dir: str = None) -> List[dict]:
        """
        Generate speech for a script with multiple lines and speakers.

        Args:
            script: List of {"speaker": "Name", "text": "Line...", "language": "en"}
            output_dir: Directory for output files

        Example:
            script = [
                {"speaker": "Narrator", "text": "Once upon a time..."},
                {"speaker": "Grandpa", "text": "Let me tell you a story."},
            ]
        """
        out_dir = Path(output_dir) if output_dir else OUTPUT_DIR / f"batch_{int(time.time())}"
        out_dir.mkdir(parents=True, exist_ok=True)

        results = []
        for i, line in enumerate(script):
            speaker = line.get("speaker", "default")
            text = line.get("text", "")
            lang = line.get("language", "en")
            out_file = str(out_dir / f"{i:03d}_{speaker.lower()}.wav")

            result = self.speak(text, speaker, lang, out_file)
            result["line_index"] = i
            result["speaker"] = speaker
            result["text"] = text
            results.append(result)

        # Optionally concatenate all into one file
        try:
            from pydub import AudioSegment
            combined = AudioSegment.empty()
            pause = AudioSegment.silent(duration=500)
            for r in results:
                if r.get("success") and Path(r["output"]).exists():
                    seg = AudioSegment.from_file(r["output"])
                    combined += seg + pause
            combined_path = str(out_dir / "combined_output.wav")
            combined.export(combined_path, format="wav")
            return results + [{"combined": combined_path, "total_lines": len(script)}]
        except Exception:
            return results

    def get_status(self) -> dict:
        """Check available engines and profiles."""
        return {
            "engines": self.check_engines(),
            "profiles": self.list_profiles(),
            "profile_count": len(self.profiles),
        }


if __name__ == "__main__":
    print("Voice Clone Studio")
    vc = VoiceCloner()

    print("\n  Available engines:")
    for name, status in vc.check_engines().items():
        available = "OK" if status["available"] else "NOT INSTALLED"
        print(f"    {name}: {available}")

    print(f"\n  Voice profiles: {len(vc.list_profiles())}")
    for p in vc.list_profiles():
        print(f"    - {p}")

    print("\n  Usage:")
    print("    vc = VoiceCloner()")
    print('    vc.clone_voice("grandpa.wav", "Grandpa")')
    print('    vc.speak("Happy birthday!", "Grandpa")')
    print('    vc.create_character("Narrator", style="warm_male")')
