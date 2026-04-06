"""
Robin Voice Daemon -- Always-on voice interface for Andrew.

Session 133: Phase 1 of Andrew-Readiness (ADR-020).
Upgrades voice_gateway.py from prototype to persistent service.

Architecture:
    sounddevice (continuous) -> energy VAD (numpy) -> faster-whisper
    -> wake-word check -> command capture -> Ollama intent routing
    -> Robin task queue -> pyttsx3 voice response

Key differences from voice_gateway.py:
    - Runs as a daemon (not one-shot)
    - Energy-based VAD (no torch dependency)
    - Voice response after every action (pyttsx3)
    - Open-ended intent routing (not 8 fixed intents)
    - Graceful degradation announcements
    - Configurable via JSON (Andrew's preferences)

Usage:
    python -m rudy.voice_daemon              # Start daemon
    python -m rudy.voice_daemon --test-mic   # Test microphone
    python -m rudy.voice_daemon --test-tts   # Test voice output
"""

import json
import logging
import queue
import threading
import time
import tempfile
import wave
from pathlib import Path

import numpy as np

try:
    from rudy.paths import RUDY_DATA, RUDY_LOGS
except ImportError:
    RUDY_DATA = Path(__file__).resolve().parent.parent / "rudy-data"
    RUDY_LOGS = RUDY_DATA / "logs"

log = logging.getLogger("voice_daemon")

try:
    from rudy.voice_health import VoiceHealthMonitor
    _HAS_HEALTH = True
except ImportError:
    _HAS_HEALTH = False

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

DEFAULT_CONFIG = {
    "wake_word": "hey rudy",
    "sample_rate": 16000,
    "energy_threshold": 500,
    "silence_duration": 1.5,
    "max_command_duration": 15.0,
    "listen_chunk_seconds": 2.0,
    "whisper_model": "small.en",
    "whisper_device": "cpu",
    "whisper_compute_type": "int8",
    "ollama_model": "qwen2.5:7b",
    "ollama_host": "http://localhost:11434",
    "tts_rate": 160,
    "tts_voice_id": 0,
    "user_name": "Andrew",
    "caregiver_name": None,
    "morning_briefing_time": "07:30",
    "check_in_interval_hours": 4,
    "task_queue_dir": None,
}

CONFIG_PATH = RUDY_DATA / "voice-daemon-config.json"


def load_config():
    """Load config from JSON file, falling back to defaults."""
    config = DEFAULT_CONFIG.copy()
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                user_config = json.load(f)
            config.update(user_config)
        except Exception as e:
            log.warning("Config load failed, using defaults: %s", e)
    return config

def save_config(config):
    """Persist config to JSON."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


# -------------------------------------------------------------------
# Voice Activity Detection (energy-based, no torch needed)
# -------------------------------------------------------------------

class EnergyVAD:
    """Simple energy-based voice activity detector using numpy.

    Detects speech by comparing RMS energy of audio chunks
    against a threshold. No ML model required -- works on
    any hardware. Adaptive threshold adjusts to ambient noise.
    """

    def __init__(self, threshold=500, silence_dur=1.5,
                 sample_rate=16000):
        self.threshold = threshold
        self.silence_dur = silence_dur
        self.sample_rate = sample_rate
        self._ambient_rms = 0.0
        self._calibrated = False

    def calibrate(self, audio_chunk):
        """Calibrate ambient noise level from a quiet sample."""
        rms = self._rms(audio_chunk)
        self._ambient_rms = rms
        self.threshold = max(rms * 3, 300)
        self._calibrated = True
        log.info("[VAD] Calibrated: ambient=%.0f, threshold=%.0f",
                 rms, self.threshold)

    def is_speech(self, audio_chunk):
        """Return True if chunk contains speech."""
        return self._rms(audio_chunk) > self.threshold

    def _rms(self, audio_chunk):
        """Root mean square energy of int16 audio."""
        if isinstance(audio_chunk, bytes):
            audio_chunk = np.frombuffer(audio_chunk, dtype=np.int16)
        return float(np.sqrt(np.mean(audio_chunk.astype(np.float32) ** 2)))


# -------------------------------------------------------------------
# STT Engine (faster-whisper)
# -------------------------------------------------------------------

class STTEngine:
    """Speech-to-text using faster-whisper. Lazy-loads model."""

    def __init__(self, model_size="small.en", device="cpu",
                 compute_type="int8"):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            log.info("[STT] Loading %s model...", self.model_size)
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
            log.info("[STT] Model loaded.")
        return self._model

    def transcribe(self, wav_path):
        """Transcribe WAV file to text."""
        model = self._load()
        segments, info = model.transcribe(str(wav_path), beam_size=3)
        text = " ".join(seg.text.strip() for seg in segments)
        log.info("[STT] (%s, %.1fs): %s",
                 info.language, info.duration, text[:100])
        return text


# -------------------------------------------------------------------
# TTS Engine (pyttsx3 -- offline, zero-latency)
# -------------------------------------------------------------------

class TTSEngine:
    """Text-to-speech using pyttsx3 (Windows SAPI5, offline)."""

    def __init__(self, rate=160, voice_id=0):
        self._rate = rate
        self._voice_id = voice_id
        self._engine = None

    def _load(self):
        if self._engine is None:
            import pyttsx3
            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", self._rate)
            voices = self._engine.getProperty("voices")
            if self._voice_id < len(voices):
                self._engine.setProperty(
                    "voice", voices[self._voice_id].id
                )
            log.info("[TTS] Engine initialized (rate=%d)", self._rate)
        return self._engine

    def speak(self, text):
        """Speak text aloud through speakers."""
        engine = self._load()
        log.info("[TTS] Speaking: %s", text[:80])
        engine.say(text)
        engine.runAndWait()

    def speak_async(self, text):
        """Speak in a background thread (non-blocking)."""
        t = threading.Thread(target=self.speak, args=(text,),
                             daemon=True)
        t.start()


# -------------------------------------------------------------------
# Intent Router (open-ended via Ollama)
# -------------------------------------------------------------------

INTENT_PROMPT = """You are Robin's intent router. Given a voice command
from {user_name}, classify it into ONE of these domains and extract
the action. Respond ONLY with valid JSON.

Domains:
- communication: email, message, call, text someone
- information: search, look up, what is, who is, weather, news
- schedule: calendar, reminder, alarm, appointment, timer
- smart_home: lights, temperature, lock, TV, music, volume
- health: medication, doctor, prescription, vitals, check-in
- file_ops: find file, open, save, read document
- system: status, help, settings, what can you do
- emergency: help me, call caregiver, I need help, 911

Output format:
{{"domain": "...", "action": "...", "entities": {{}},
  "confidence": 0.0, "clarification_needed": false,
  "clarification_question": null}}

Voice command: {text}"""

class IntentRouter:
    """Route voice commands to Robin domains via Ollama."""

    def __init__(self, model="qwen2.5:7b",
                 host="http://localhost:11434",
                 user_name="Andrew"):
        self.model = model
        self.host = host
        self.user_name = user_name

    def route(self, text):
        """Parse text into a structured intent via Ollama."""
        import urllib.request
        prompt = INTENT_PROMPT.format(
            user_name=self.user_name, text=text
        )
        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1},
        }).encode()
        req = urllib.request.Request(
            f"{self.host}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read())
            raw = body.get("response", "")
            intent = json.loads(raw)
            intent.setdefault("raw_text", text)
            log.info("[Intent] %s (conf=%.2f): %s",
                     intent.get("domain"), intent.get("confidence", 0),
                     intent.get("action", ""))
            return intent
        except (json.JSONDecodeError, KeyError) as e:
            log.warning("[Intent] Parse failed: %s", e)
            return {"domain": "system", "action": "unknown",
                    "entities": {}, "confidence": 0.0,
                    "raw_text": text, "parse_error": str(e)}
        except Exception as e:
            log.error("[Intent] Ollama error: %s", e)
            return {"domain": "system", "action": "unknown",
                    "entities": {}, "confidence": 0.0,
                    "raw_text": text, "error": str(e)}


# -------------------------------------------------------------------
# Task Queue Integration
# -------------------------------------------------------------------

def queue_task(intent, config):
    """Write intent as a task to Robin's queue."""
    tq_dir = config.get("task_queue_dir")
    if tq_dir:
        tq_path = Path(tq_dir)
    else:
        try:
            from rudy.paths import ROBIN_TASKQUEUE
            tq_path = ROBIN_TASKQUEUE
        except ImportError:
            tq_path = RUDY_DATA / "robin-taskqueue"
    tq_path.mkdir(parents=True, exist_ok=True)
    task_id = int(time.time() * 1000)
    task = {
        "id": task_id,
        "source": "voice_daemon",
        "domain": intent.get("domain", "unknown"),
        "action": intent.get("action", ""),
        "priority": "high" if intent.get("domain") == "emergency"
                    else "normal",
        "status": "pending",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "payload": intent,
    }
    task_path = tq_path / f"{task_id}-voice.json"
    task_path.write_text(json.dumps(task, indent=2), encoding="utf-8")
    log.info("[Queue] Task %d queued: %s/%s",
             task_id, intent.get("domain"), intent.get("action"))
    return task


# -------------------------------------------------------------------
# Event Bus (for Andrew Console visibility)
# -------------------------------------------------------------------

_event_listeners = []


def on_event(callback):
    """Register a callback for daemon events."""
    _event_listeners.append(callback)


def _emit(event_type, data=None):
    """Emit event to all listeners (console, log, etc.)."""
    event = {
        "type": event_type,
        "timestamp": time.strftime("%H:%M:%S"),
        "data": data or {},
    }
    for cb in _event_listeners:
        try:
            cb(event)
        except Exception:
            pass


# -------------------------------------------------------------------
# Main Daemon
# -------------------------------------------------------------------

class VoiceDaemon:
    """Always-on voice interface daemon for Andrew.

    Listens continuously, detects wake word, captures command,
    routes intent, queues task, and speaks result back.
    """

    def __init__(self, config=None):
        self.config = config or load_config()
        self.vad = EnergyVAD(
            threshold=self.config["energy_threshold"],
            silence_dur=self.config["silence_duration"],
            sample_rate=self.config["sample_rate"],
        )
        self.stt = STTEngine(
            model_size=self.config["whisper_model"],
            device=self.config["whisper_device"],
            compute_type=self.config["whisper_compute_type"],
        )
        self.tts = TTSEngine(
            rate=self.config["tts_rate"],
            voice_id=self.config["tts_voice_id"],
        )
        self.router = IntentRouter(
            model=self.config["ollama_model"],
            host=self.config["ollama_host"],
            user_name=self.config["user_name"],
        )
        self._running = False
        self._audio_queue = queue.Queue()
        self._state = "idle"  # idle, listening, processing
        # Health monitor integration (S134)
        self._health_monitor = None
        if _HAS_HEALTH:
            try:
                self._health_monitor = VoiceHealthMonitor(
                    self.tts, self.config
                )
            except Exception as e:
                log.warning("[Daemon] Health monitor init failed: %s", e)
        self._stats = {
            "commands_processed": 0,
            "wake_detections": 0,
            "errors": 0,
            "uptime_start": None,
        }

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, new_state):
        old = self._state
        self._state = new_state
        if old != new_state:
            _emit("state_change", {"from": old, "to": new_state})

    def _record_chunk(self, duration):
        """Record a chunk of audio, return numpy int16 array."""
        import sounddevice as sd
        audio = sd.rec(
            int(duration * self.config["sample_rate"]),
            samplerate=self.config["sample_rate"],
            channels=1, dtype="int16",
        )
        sd.wait()
        return audio.flatten()

    def _save_wav(self, audio, path):
        """Save int16 numpy array as WAV."""
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.config["sample_rate"])
            wf.writeframes(audio.tobytes())
        return path

    def _capture_command(self):
        """After wake word detected, capture full command until silence."""
        _emit("listening", {"msg": "Listening for command..."})
        self.state = "listening"
        sr = self.config["sample_rate"]
        max_dur = self.config["max_command_duration"]
        silence_dur = self.config["silence_duration"]

        chunks = []
        silence_samples = 0
        total_samples = 0
        chunk_size = int(0.5 * sr)  # 500ms chunks

        while total_samples < max_dur * sr:
            import sounddevice as sd
            chunk = sd.rec(chunk_size, samplerate=sr,
                           channels=1, dtype="int16")
            sd.wait()
            chunk = chunk.flatten()
            chunks.append(chunk)
            total_samples += len(chunk)

            if not self.vad.is_speech(chunk):
                silence_samples += len(chunk)
                if silence_samples >= silence_dur * sr:
                    break
            else:
                silence_samples = 0

        return np.concatenate(chunks) if chunks else np.array([], dtype=np.int16)

    def _process_command(self, audio):
        """Transcribe, route intent, queue task, speak result."""
        self.state = "processing"
        _emit("processing", {"msg": "Processing command..."})

        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "command.wav"
            self._save_wav(audio, wav_path)
            text = self.stt.transcribe(wav_path)

        if not text.strip():
            self.tts.speak("I didn't catch that. Could you say it again?")
            _emit("error", {"msg": "Empty transcription"})
            self._stats["errors"] += 1
            return

        _emit("transcribed", {"text": text})

        # Route intent
        intent = self.router.route(text)
        _emit("intent", {"intent": intent})

        # Handle emergency immediately
        if intent.get("domain") == "emergency":
            self.tts.speak("I hear you. Getting help now.")
            _emit("emergency", {"intent": intent})

        # Handle clarification
        if intent.get("clarification_needed"):
            question = intent.get("clarification_question",
                                  "Could you tell me more?")
            self.tts.speak(question)
            _emit("clarification", {"question": question})
            return

        # Queue task for Robin
        task = queue_task(intent, self.config)
        self._stats["commands_processed"] += 1

        # Voice confirmation
        domain = intent.get("domain", "unknown")
        action = intent.get("action", text[:50])
        confirmations = {
            "communication": "I'll handle that message for you.",
            "information": "Let me look that up.",
            "schedule": "I'll take care of that.",
            "smart_home": "On it.",
            "health": "Checking on that now.",
            "file_ops": "Working on that file.",
            "system": "Here's what I know.",
        }
        msg = confirmations.get(domain, f"Got it. Working on: {action}")
        self.tts.speak(msg)
        _emit("confirmed", {"domain": domain, "action": action,
                             "task_id": task.get("id")})

    def calibrate(self):
        """Calibrate VAD to ambient noise level."""
        _emit("calibrating", {"msg": "Calibrating microphone..."})
        self.tts.speak("Calibrating. Please stay quiet for a moment.")
        time.sleep(1)
        ambient = self._record_chunk(3.0)
        self.vad.calibrate(ambient)
        self.tts.speak("Calibration complete. Say 'hey Rudy' when "
                       "you need me.")
        _emit("calibrated", {"threshold": self.vad.threshold})

    def run(self):
        """Main daemon loop."""
        self._running = True
        self._stats["uptime_start"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        wake = self.config["wake_word"].lower()
        chunk_dur = self.config["listen_chunk_seconds"]

        log.info("[Daemon] Starting voice daemon for %s",
                 self.config["user_name"])
        _emit("started", {"user": self.config["user_name"],
                           "wake_word": wake})

        self.calibrate()

        # Health announcement and check-in scheduler (S134)
        if self._health_monitor:
            try:
                self._health_monitor.startup_announcement()
                self._health_monitor.start_checkins()
                self._health_monitor.start_periodic_monitoring()
            except Exception as e:
                log.warning("[Daemon] Health startup failed: %s", e)

        while self._running:
            try:
                self.state = "idle"
                chunk = self._record_chunk(chunk_dur)

                if not self.vad.is_speech(chunk):
                    continue

                # Speech detected -- transcribe to check for wake word
                with tempfile.TemporaryDirectory() as tmp:
                    wav_path = Path(tmp) / "listen.wav"
                    self._save_wav(chunk, wav_path)
                    text = self.stt.transcribe(wav_path).lower().strip()

                if wake in text:
                    self._stats["wake_detections"] += 1
                    # Acknowledge check-in on voice activity (S134)
                    if self._health_monitor:
                        self._health_monitor.on_voice_activity()
                    _emit("wake_word", {"text": text})
                    log.info("[Daemon] Wake word detected: %s", text)

                    # Play acknowledgment tone via TTS
                    self.tts.speak("Yes?")

                    # Capture the actual command
                    command_audio = self._capture_command()
                    if len(command_audio) > 0:
                        self._process_command(command_audio)

            except KeyboardInterrupt:
                break
            except Exception as e:
                self._stats["errors"] += 1
                log.error("[Daemon] Error: %s", e)
                _emit("error", {"msg": str(e)})
                time.sleep(2)

        # Stop health monitor (S134)
        if self._health_monitor:
            self._health_monitor.stop_checkins()
        self.state = "stopped"
        _emit("stopped", {"stats": self._stats})
        log.info("[Daemon] Stopped. Stats: %s", self._stats)

    def stop(self):
        """Signal the daemon to stop."""
        self._running = False


# -------------------------------------------------------------------
# Andrew Console -- Visibility into Robin's state
# -------------------------------------------------------------------

class AndrewConsole:
    """Simple console display showing Robin's voice daemon state.

    Provides real-time visibility for Andrew (or caregivers)
    into what Robin is hearing, thinking, and doing.
    Designed for readability -- large text, clear status,
    minimal clutter.
    """

    STATUS_ICONS = {
        "idle": "[READY]",
        "listening": "[LISTENING...]",
        "processing": "[THINKING...]",
        "stopped": "[STOPPED]",
    }

    def __init__(self):
        self._history = []
        self._max_history = 20
        on_event(self._handle_event)

    def _handle_event(self, event):
        """Process daemon events for display."""
        etype = event["type"]
        ts = event["timestamp"]
        data = event.get("data", {})

        if etype == "started":
            self._print_banner(data)
        elif etype == "state_change":
            icon = self.STATUS_ICONS.get(data.get("to"), "")
            self._print_status(f"{icon}")
        elif etype == "wake_word":
            self._print_line(ts, "HEARD", "Wake word detected")
        elif etype == "listening":
            self._print_line(ts, "LISTEN", data.get("msg", ""))
        elif etype == "transcribed":
            text = data.get("text", "")
            self._print_line(ts, "YOU SAID", f'"{text}"')
            self._add_history("you", text)
        elif etype == "intent":
            intent = data.get("intent", {})
            domain = intent.get("domain", "?")
            action = intent.get("action", "?")
            conf = intent.get("confidence", 0)
            self._print_line(ts, "UNDERSTOOD",
                             f"{domain} -> {action} ({conf:.0%})")
        elif etype == "confirmed":
            domain = data.get("domain", "")
            action = data.get("action", "")
            self._print_line(ts, "ROBIN", f"Working on: {action}")
            self._add_history("robin", f"[{domain}] {action}")
        elif etype == "emergency":
            self._print_line(ts, "!!! EMERGENCY !!!",
                             "Contacting help...")
        elif etype == "error":
            self._print_line(ts, "NOTE", data.get("msg", ""))
        elif etype == "calibrating":
            self._print_line(ts, "SETUP", data.get("msg", ""))
        elif etype == "calibrated":
            self._print_line(ts, "SETUP",
                             "Microphone ready. Listening for wake word.")
        elif etype == "stopped":
            stats = data.get("stats", {})
            self._print_line(ts, "STOPPED",
                             f"Commands: {stats.get('commands_processed', 0)}")

    def _print_banner(self, data):
        """Print startup banner."""
        user = data.get("user", "User")
        wake = data.get("wake_word", "hey rudy")
        print()
        print("=" * 52)
        print("  ROBIN Voice Assistant")
        print(f"  Ready for: {user}")
        print(f"  Say \"{wake}\" to begin")
        print("=" * 52)
        print()

    def _print_status(self, status_text):
        """Print current status."""
        print(f"\r  {status_text}                    ", end="", flush=True)

    def _print_line(self, ts, label, msg):
        """Print a timestamped event line."""
        print(f"\n  {ts}  {label:>12s}  {msg}")

    def _add_history(self, speaker, text):
        """Track conversation history."""
        self._history.append({"speaker": speaker, "text": text})
        if len(self._history) > self._max_history:
            self._history.pop(0)

    def show_history(self):
        """Display recent conversation history."""
        print("\n  --- Recent Activity ---")
        for entry in self._history[-10:]:
            speaker = "You" if entry["speaker"] == "you" else "Robin"
            print(f"    {speaker}: {entry['text']}")
        if not self._history:
            print("    (no activity yet)")
        print()


# -------------------------------------------------------------------
# CLI Entry Point
# -------------------------------------------------------------------

def main():
    """CLI entry point for the voice daemon."""
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(
                RUDY_LOGS / "voice-daemon.log", encoding="utf-8"
            ),
            logging.StreamHandler(),
        ],
    )

    p = argparse.ArgumentParser(
        description="Robin Voice Daemon -- Andrew's voice interface"
    )
    p.add_argument("--test-mic", action="store_true",
                   help="Test microphone capture")
    p.add_argument("--test-tts", action="store_true",
                   help="Test voice output")
    p.add_argument("--config", type=str, default=None,
                   help="Path to config JSON file")
    p.add_argument("--user", type=str, default=None,
                   help="User name (overrides config)")
    p.add_argument("--wake-word", type=str, default=None,
                   help="Wake word (overrides config)")
    args = p.parse_args()

    config = load_config()
    if args.config:
        with open(args.config) as f:
            config.update(json.load(f))
    if args.user:
        config["user_name"] = args.user
    if args.wake_word:
        config["wake_word"] = args.wake_word

    if args.test_mic:
        print("Testing microphone... speak now (3 seconds)")
        import sounddevice as sd
        audio = sd.rec(int(3 * 16000), samplerate=16000,
                       channels=1, dtype="int16")
        sd.wait()
        rms = float(np.sqrt(np.mean(
            audio.astype(np.float32) ** 2
        )))
        print(f"Recorded 3s. RMS energy: {rms:.0f}")
        print("  > 300 = speech likely detected")
        print("  < 300 = quiet / no speech")
        return

    if args.test_tts:
        tts = TTSEngine(rate=config["tts_rate"],
                        voice_id=config["tts_voice_id"])
        tts.speak(f"Hello {config['user_name']}. "
                  f"Robin voice system is working.")
        return

    # Start daemon with Andrew Console
    _console = AndrewConsole()  # noqa: F841 side-effect: registers event listeners
    daemon = VoiceDaemon(config)

    try:
        daemon.run()
    except KeyboardInterrupt:
        daemon.stop()
        print("\n  Robin voice daemon stopped. Goodbye.")


if __name__ == "__main__":
    main()
