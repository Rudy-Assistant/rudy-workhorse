"""
Voice Gateway — Mic capture → STT → Intent Parse → Robin task queue.

Session 64: Prototype. Closes the voice-to-action loop for Robin.

Architecture:
    Mic (sounddevice) → faster-whisper (tiny.en) → Ollama (qwen2.5:7b)
    → Robin task queue (rudy-data/robin-taskqueue/)

Usage:
    # One-shot: record, transcribe, parse, queue
    python -m rudy.voice_gateway --once

    # Continuous listening with wake word
    python -m rudy.voice_gateway --listen --wake-word "hey rudy"

    # Just transcribe (no intent parsing)
    python -m rudy.voice_gateway --transcribe-only
"""

import json
import logging
import tempfile
import time
import wave
from pathlib import Path

log = logging.getLogger("voice_gateway")

# ---------------------------------------------------------------------------
# Audio capture
# ---------------------------------------------------------------------------

def record_audio(duration: float = 5.0, sample_rate: int = 16000) -> bytes:
    """Record audio from default mic, return raw PCM bytes."""
    import sounddevice as sd

    log.info("[Voice] Recording %.1fs at %dHz...", duration, sample_rate)
    audio = sd.rec(
        int(duration * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype="int16",
    )
    sd.wait()
    log.info("[Voice] Recording complete — %d samples", len(audio))
    return audio.tobytes()


def save_wav(pcm_bytes: bytes, path: Path, sample_rate: int = 16000) -> Path:
    """Save raw PCM bytes as a WAV file."""
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return path

# ---------------------------------------------------------------------------
# Speech-to-Text (faster-whisper)
# ---------------------------------------------------------------------------

_whisper_model = None


def _get_whisper_model():
    """Lazy-load the Whisper model (tiny.en for speed)."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        log.info("[Voice] Loading faster-whisper tiny.en model...")
        _whisper_model = WhisperModel(
            "tiny.en", device="cpu", compute_type="int8"
        )
        log.info("[Voice] Model loaded.")
    return _whisper_model


def transcribe(wav_path: Path) -> str:
    """Transcribe a WAV file to text using faster-whisper."""
    model = _get_whisper_model()
    segments, info = model.transcribe(str(wav_path), beam_size=3)
    text = " ".join(seg.text.strip() for seg in segments)
    log.info("[Voice] Transcribed (%s, %.1fs): %s",
             info.language, info.duration, text)
    return text

# ---------------------------------------------------------------------------
# Intent parsing (Ollama)
# ---------------------------------------------------------------------------

INTENT_PROMPT = """You are Robin's intent parser. Given a voice command, extract:
1. "intent": one of [send_email, check_calendar, search_web, run_task,
   check_weather, set_reminder, ask_question, unknown]
2. "entities": dict of extracted parameters (recipient, subject, query, etc.)
3. "confidence": float 0-1
4. "raw_text": the original transcription

Return ONLY valid JSON, no markdown fences.

Voice command: {text}"""


def parse_intent(text: str) -> dict:
    """Parse transcribed text into a structured intent via Ollama."""
    import urllib.request
    prompt = INTENT_PROMPT.format(text=text)
    payload = json.dumps({
        "model": "qwen2.5:7b",
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1},
    }).encode()
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
        raw = body.get("response", "")
        # Try to parse JSON from response
        intent = json.loads(raw)
        intent.setdefault("raw_text", text)
        log.info("[Voice] Intent: %s (conf=%.2f)",
                 intent.get("intent"), intent.get("confidence", 0))
        return intent
    except (json.JSONDecodeError, KeyError) as e:
        log.warning("[Voice] Intent parse failed: %s — raw: %s", e, raw[:200])
        return {"intent": "unknown", "entities": {},
                "confidence": 0.0, "raw_text": text, "parse_error": str(e)}
    except Exception as e:
        log.error("[Voice] Ollama request failed: %s", e)
        return {"intent": "unknown", "entities": {},
                "confidence": 0.0, "raw_text": text, "error": str(e)}

# ---------------------------------------------------------------------------
# Robin task queue integration
# ---------------------------------------------------------------------------

def queue_for_robin(intent: dict) -> Path:
    """Write an intent as a task to Robin's task queue."""
    try:
        from rudy.paths import ROBIN_TASKQUEUE
    except ImportError:
        ROBIN_TASKQUEUE = (Path(__file__).resolve().parent.parent
                          / "rudy-data" / "robin-taskqueue")
    ROBIN_TASKQUEUE.mkdir(parents=True, exist_ok=True)
    task_id = int(time.time() * 1000)
    task = {
        "id": task_id,
        "source": "voice_gateway",
        "type": intent.get("intent", "unknown"),
        "priority": "normal",
        "status": "pending",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "payload": intent,
    }
    task_path = ROBIN_TASKQUEUE / f"{task_id}-voice-task.json"
    task_path.write_text(json.dumps(task, indent=2), encoding="utf-8")
    log.info("[Voice] Queued task %d for Robin: %s", task_id, intent.get("intent"))
    return task_path

# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def voice_to_task(duration: float = 5.0) -> dict:
    """Full pipeline: record → transcribe → parse intent → queue for Robin."""
    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "voice_input.wav"
        pcm = record_audio(duration=duration)
        save_wav(pcm, wav_path)
        text = transcribe(wav_path)
        if not text.strip():
            log.warning("[Voice] Empty transcription — no speech detected.")
            return {"status": "empty", "text": ""}
        intent = parse_intent(text)
        task_path = queue_for_robin(intent)
        return {
            "status": "queued",
            "text": text,
            "intent": intent,
            "task_file": str(task_path),
        }

def listen_loop(wake_word: str = "hey rudy", duration: float = 5.0):
    """Continuous listen loop with wake word detection."""
    log.info("[Voice] Listening for wake word '%s'...", wake_word)
    while True:
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "listen.wav"
            pcm = record_audio(duration=2.0)  # short listen window
            save_wav(pcm, wav_path)
            text = transcribe(wav_path).lower().strip()
            if wake_word.lower() in text:
                log.info("[Voice] Wake word detected! Listening for command...")
                result = voice_to_task(duration=duration)
                log.info("[Voice] Result: %s", json.dumps(result, indent=2))
            else:
                time.sleep(0.5)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(message)s")
    p = argparse.ArgumentParser(description="Rudy Voice Gateway")
    p.add_argument("--once", action="store_true",
                   help="Record once, transcribe, parse, queue")
    p.add_argument("--listen", action="store_true",
                   help="Continuous wake-word listening")
    p.add_argument("--transcribe-only", action="store_true",
                   help="Record and transcribe only, no intent parsing")
    p.add_argument("--wake-word", default="hey rudy",
                   help="Wake word for listen mode (default: 'hey rudy')")
    p.add_argument("--duration", type=float, default=5.0,
                   help="Recording duration in seconds (default: 5)")
    args = p.parse_args()

    if args.once:
        result = voice_to_task(duration=args.duration)
        print(json.dumps(result, indent=2))
    elif args.listen:
        listen_loop(wake_word=args.wake_word, duration=args.duration)
    elif args.transcribe_only:
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "voice.wav"
            pcm = record_audio(duration=args.duration)
            save_wav(pcm, wav_path)
            text = transcribe(wav_path)
            print(json.dumps({"text": text}, indent=2))
    else:
        p.print_help()
