"""
Local AI Engine — Offline intelligence for The Workhorse.

Runs a quantized LLM entirely on CPU, giving Rudy independent reasoning
capability even during internet outages.

Capabilities (all 100% offline):
  - Intent classification: Understand what a command/alert means
  - Decision making: Should we restart a service? Escalate? Wait?
  - Text summarization: Condense logs, alerts, and reports
  - Alert triage: Classify severity of security/system events
  - Natural language generation: Write email subjects, alert messages
  - Conversation: Handle basic family assistant queries offline

Architecture (dual backend):
  Primary: Ollama HTTP API (http://localhost:11434)
    - Manages model lifecycle, auto-loads, better memory management
    - Models: phi3:mini, mistral, tinyllama (pull via 'ollama pull')
  Fallback: llama-cpp-python (GGUF format)
    - Direct CPU inference if Ollama is down
    - Models in rudy-data/models/*.gguf
  Response caching for repeated queries

Hardware target: AMD Ryzen 5 5600U, 16GB RAM, CPU-only.
"""

import json
import hashlib
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from rudy.paths import RUDY_LOGS, RUDY_DATA  # noqa: E402

MODELS_DIR = RUDY_DATA / "models"
LOGS = RUDY_LOGS
CACHE_DIR = RUDY_DATA / "ai-cache"

# Model registry — download URLs and expected sizes
MODEL_REGISTRY = {
    "phi3-mini": {
        "filename": "Phi-3-mini-4k-instruct-q4.gguf",
        "url": "https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-q4.gguf",
        "size_gb": 2.3,
        "ram_needed_gb": 4.0,
        "description": "Fast and capable — best for health checks, classification, short tasks",
        "n_ctx": 4096,
        "speed_estimate": "5-6 tok/s on Ryzen 5 5600U",
    },
    "mistral-7b": {
        "filename": "mistral-7b-instruct-v0.2.Q4_K_M.gguf",
        "url": "https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/resolve/main/mistral-7b-instruct-v0.2.Q4_K_M.gguf",
        "size_gb": 4.4,
        "ram_needed_gb": 7.0,
        "description": "Smarter — best for complex reasoning, summarization, conversation",
        "n_ctx": 4096,
        "speed_estimate": "2-3 tok/s on Ryzen 5 5600U",
    },
    "tinyllama": {
        "filename": "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
        "url": "https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
        "size_gb": 0.7,
        "ram_needed_gb": 2.0,
        "description": "Ultra-light — emergency fallback, very fast but less capable",
        "n_ctx": 2048,
        "speed_estimate": "15-20 tok/s on Ryzen 5 5600U",
    },
}

# System prompts for different roles
SYSTEM_PROMPTS = {
    "general": (
        "You are Rudy, a family AI assistant running on a local computer. "
        "You help the Cimino family with information, tasks, and home automation. "
        "Be concise, helpful, and friendly. If you're unsure, say so."
    ),
    "security": (
        "You are Rudy's security analysis engine. Analyze the following security "
        "event and provide: 1) Severity (critical/high/medium/low/info), "
        "2) Assessment (what happened), 3) Recommended action (ignore/monitor/alert/block). "
        "Be concise. Prioritize safety."
    ),
    "ops": (
        "You are Rudy's system operations engine. Analyze system health data "
        "and decide: 1) Is intervention needed? 2) What action to take "
        "(restart_service/alert_chris/escalate/monitor/ignore). "
        "3) Brief reason. Be decisive and concise."
    ),
    "summarize": (
        "Summarize the following text concisely. Focus on key facts, "
        "actionable items, and important changes. Keep it under 3 sentences."
    ),
    "classify": (
        "Classify the intent of the following message. Respond with exactly one of: "
        "COMMAND, QUESTION, ALERT, STATUS_REQUEST, GREETING, UNKNOWN. "
        "Then a brief explanation."
    ),
    "triage": (
        "You are triaging an alert for the Cimino family home network. "
        "Given the alert details, respond with: SEVERITY (1-5), "
        "ACTION (ignore/log/notify/investigate/emergency), "
        "and a one-line SUMMARY."
    ),
}

def _load_json(path, default=None):
    if Path(path).exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return default if default is not None else {}

def _save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)

class ResponseCache:
    """Simple cache for repeated queries (avoids re-inference)."""

    def __init__(self, max_entries: int = 500):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.cache_file = CACHE_DIR / "response-cache.json"
        self.cache = _load_json(self.cache_file, {"entries": {}})
        self.max_entries = max_entries

    def _key(self, prompt: str, role: str) -> str:
        return hashlib.md5(f"{role}:{prompt}".encode()).hexdigest()[:16]

    def get(self, prompt: str, role: str = "general") -> Optional[str]:
        key = self._key(prompt, role)
        entry = self.cache.get("entries", {}).get(key)
        if entry:
            # Cache entries expire after 1 hour
            cached_time = entry.get("time", "")
            try:
                if (datetime.now() - datetime.fromisoformat(cached_time)).total_seconds() < 3600:
                    return entry.get("response")
            except Exception:
                pass
        return None

    def put(self, prompt: str, role: str, response: str):
        key = self._key(prompt, role)
        self.cache.setdefault("entries", {})[key] = {
            "response": response,
            "time": datetime.now().isoformat(),
            "role": role,
        }
        # Trim old entries
        entries = self.cache["entries"]
        if len(entries) > self.max_entries:
            sorted_keys = sorted(entries.keys(),
                                 key=lambda k: entries[k].get("time", ""))
            for old_key in sorted_keys[:len(entries) - self.max_entries]:
                del entries[old_key]
        _save_json(self.cache_file, self.cache)

# Ollama model name mapping (our names → Ollama names)
OLLAMA_MODEL_MAP = {
    "phi3-mini": "phi3:mini",
    "mistral-7b": "mistral",
    "tinyllama": "tinyllama",
}

OLLAMA_URL = "http://localhost:11434"

class OllamaBackend:
    """Ollama HTTP API backend — primary inference engine."""

    def __init__(self):
        self._available = None  # Cache availability check

    def is_available(self) -> bool:
        """Check if Ollama server is running."""
        try:
            import urllib.request
            req = urllib.request.Request(f"{OLLAMA_URL}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                self._available = resp.status == 200
                return self._available
        except Exception:
            self._available = False
            return False

    def list_models(self) -> list:
        """List locally available Ollama models."""
        try:
            import urllib.request
            req = urllib.request.Request(f"{OLLAMA_URL}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                return [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            return []

    def has_model(self, model_name: str) -> bool:
        """Check if a specific model is available in Ollama."""
        ollama_name = OLLAMA_MODEL_MAP.get(model_name, model_name)
        models = self.list_models()
        return any(ollama_name in m for m in models)

    def generate(self, prompt: str, system: str = "", model_name: str = "phi3-mini",
                 max_tokens: int = 256, temperature: float = 0.3) -> str:
        """Generate a response via Ollama HTTP API."""
        import urllib.request

        ollama_name = OLLAMA_MODEL_MAP.get(model_name, model_name)

        payload = json.dumps({
            "model": ollama_name,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            }
        }).encode()

        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
            return data.get("response", "").strip()

class LocalAI:
    """
    Local LLM inference engine — Ollama primary, llama-cpp-python fallback.

    Usage:
        ai = LocalAI()
        response = ai.ask("What services are running on this PC?")
        result = ai.triage_alert("Unknown device MAC aa:bb:cc appeared at 3 AM")
        action = ai.ops_decision("RustDesk service has been down for 10 minutes")
        summary = ai.summarize("... long log output ...")
    """

    def __init__(self, default_model: str = "phi3-mini"):
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        self._llm = None  # llama-cpp fallback
        self._model_name = None
        self._cache = ResponseCache()
        self._default_model = default_model
        self._ollama = OllamaBackend()
        self._backend = None  # "ollama" or "llamacpp" — set on first use
        self._stats = {
            "total_queries": 0,
            "cache_hits": 0,
            "total_tokens_generated": 0,
            "load_time_seconds": 0,
            "backend": None,
        }

    def is_model_available(self, model_name: str = None) -> bool:
        """Check if a model file exists locally."""
        name = model_name or self._default_model
        info = MODEL_REGISTRY.get(name)
        if not info:
            return False
        return (MODELS_DIR / info["filename"]).exists()

    def list_available_models(self) -> List[dict]:
        """List all models and their local availability."""
        result = []
        for name, info in MODEL_REGISTRY.items():
            local_path = MODELS_DIR / info["filename"]
            result.append({
                "name": name,
                "filename": info["filename"],
                "size_gb": info["size_gb"],
                "ram_needed_gb": info["ram_needed_gb"],
                "available_locally": local_path.exists(),
                "local_size_mb": round(local_path.stat().st_size / 1024 / 1024, 1) if local_path.exists() else 0,
                "description": info["description"],
                "speed": info["speed_estimate"],
            })
        return result

    def download_model(self, model_name: str = None) -> dict:
        """Download a model from Hugging Face."""
        name = model_name or self._default_model
        info = MODEL_REGISTRY.get(name)
        if not info:
            return {"error": f"Unknown model: {name}"}

        dest = MODELS_DIR / info["filename"]
        if dest.exists():
            return {"status": "already_downloaded", "path": str(dest)}

        try:
            import requests
            print(f"Downloading {info['filename']} ({info['size_gb']}GB)...")
            print(f"  URL: {info['url']}")

            resp = requests.get(info["url"], stream=True, timeout=30)
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))

            downloaded = 0
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):  # 1MB chunks
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = downloaded / total * 100
                        if downloaded % (50 * 1024 * 1024) < 1024 * 1024:  # Print every ~50MB
                            print(f"  {pct:.0f}% ({downloaded // (1024*1024)}MB / {total // (1024*1024)}MB)")

            print(f"  Download complete: {dest}")
            return {"status": "downloaded", "path": str(dest),
                    "size_mb": round(dest.stat().st_size / 1024 / 1024, 1)}
        except Exception as e:
            # Clean up partial download
            if dest.exists():
                dest.unlink()
            return {"error": str(e)[:300]}

    def load_model(self, model_name: str = None, n_threads: int = 6) -> bool:
        """Load a model into memory."""
        name = model_name or self._default_model
        info = MODEL_REGISTRY.get(name)
        if not info:
            print(f"Unknown model: {name}")
            return False

        model_path = MODELS_DIR / info["filename"]
        if not model_path.exists():
            print(f"Model not found at {model_path}")
            print(f"Download it with: ai.download_model('{name}')")
            return False

        # Unload existing model if different
        if self._llm and self._model_name != name:
            del self._llm
            self._llm = None

        if self._llm and self._model_name == name:
            return True  # Already loaded

        try:
            from llama_cpp import Llama

            start = time.time()
            self._llm = Llama(
                model_path=str(model_path),
                n_ctx=info.get("n_ctx", 2048),
                n_threads=n_threads,
                n_gpu_layers=0,  # CPU only
                verbose=False,
            )
            self._model_name = name
            self._stats["load_time_seconds"] = round(time.time() - start, 2)
            print(f"Model '{name}' loaded in {self._stats['load_time_seconds']}s")
            return True
        except ImportError:
            print("llama-cpp-python not installed. Run: pip install llama-cpp-python")
            return False
        except Exception as e:
            print(f"Failed to load model: {e}")
            return False

    def _ensure_loaded(self):
        """Auto-select backend: try Ollama first, fall back to llama-cpp."""
        if self._backend == "ollama":
            return  # Already using Ollama

        # Try Ollama
        if self._ollama.is_available():
            model = self._default_model
            if self._ollama.has_model(model):
                self._backend = "ollama"
                self._model_name = model
                self._stats["backend"] = "ollama"
                return

        # Fall back to llama-cpp-python
        if self._llm is None:
            if not self.load_model():
                raise RuntimeError(
                    "No AI backend available. Either start Ollama "
                    "(ollama serve) or download a GGUF model."
                )
        self._backend = "llamacpp"
        self._stats["backend"] = "llamacpp"

    def _generate(self, prompt: str, system: str = "", max_tokens: int = 256,
                  temperature: float = 0.3) -> str:
        """Core generation — routes to Ollama or llama-cpp."""
        self._ensure_loaded()

        time.time()
        self._stats["total_queries"] += 1

        if self._backend == "ollama":
            try:
                text = self._ollama.generate(
                    prompt, system=system,
                    model_name=self._model_name or self._default_model,
                    max_tokens=max_tokens, temperature=temperature
                )
                return text
            except Exception as e:
                # Ollama failed — try falling back to llama-cpp
                if self._llm is not None or self.load_model():
                    self._backend = "llamacpp"
                    self._stats["backend"] = "llamacpp"
                    # Fall through to llama-cpp below
                else:
                    raise RuntimeError(f"Ollama failed ({e}) and no llama-cpp fallback")

        # llama-cpp-python path
        if system:
            full_prompt = f"[INST] {system}\n\n{prompt} [/INST]"
        else:
            full_prompt = f"[INST] {prompt} [/INST]"

        result = self._llm(
            full_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=["[INST]", "</s>"],
        )

        text = result["choices"][0]["text"].strip()
        tokens = result["usage"]["completion_tokens"]
        self._stats["total_tokens_generated"] += tokens

        return text

    def ask(self, prompt: str, role: str = "general",
            use_cache: bool = True, max_tokens: int = 256) -> str:
        """
        Ask the local AI a question.

        role: "general", "security", "ops", "summarize", "classify", "triage"
        """
        # Check cache
        if use_cache:
            cached = self._cache.get(prompt, role)
            if cached:
                self._stats["cache_hits"] += 1
                return cached

        system = SYSTEM_PROMPTS.get(role, SYSTEM_PROMPTS["general"])
        response = self._generate(prompt, system=system, max_tokens=max_tokens)

        # Cache the response
        if use_cache:
            self._cache.put(prompt, role, response)

        return response

    def triage_alert(self, alert_text: str) -> dict:
        """Triage a security/system alert and return structured result."""
        response = self.ask(alert_text, role="triage", max_tokens=100)

        # Parse structured response
        result = {
            "raw": response,
            "severity": 3,  # Default medium
            "action": "log",
            "summary": response,
        }

        # Try to extract structured fields
        for line in response.split("\n"):
            line_upper = line.strip().upper()
            if "SEVERITY" in line_upper:
                for digit in line:
                    if digit.isdigit():
                        result["severity"] = int(digit)
                        break
            elif "ACTION" in line_upper:
                for action in ["ignore", "log", "notify", "investigate", "emergency"]:
                    if action in line.lower():
                        result["action"] = action
                        break
            elif "SUMMARY" in line_upper:
                result["summary"] = line.split(":", 1)[-1].strip() if ":" in line else line.strip()

        return result

    def ops_decision(self, situation: str) -> dict:
        """Make an operational decision about a system situation."""
        response = self.ask(situation, role="ops", max_tokens=150)

        result = {
            "raw": response,
            "needs_intervention": True,
            "action": "monitor",
            "reason": response,
        }

        response_lower = response.lower()
        if "restart" in response_lower:
            result["action"] = "restart_service"
        elif "alert" in response_lower or "notify" in response_lower:
            result["action"] = "alert_chris"
        elif "escalate" in response_lower or "emergency" in response_lower:
            result["action"] = "escalate"
        elif "ignore" in response_lower or "no intervention" in response_lower:
            result["action"] = "ignore"
            result["needs_intervention"] = False
        elif "monitor" in response_lower or "watch" in response_lower:
            result["action"] = "monitor"
            result["needs_intervention"] = False

        return result

    def summarize(self, text: str, max_length: int = 150) -> str:
        """Summarize text concisely."""
        if len(text) > 3000:
            text = text[:3000] + "... [truncated]"
        return self.ask(text, role="summarize", max_tokens=max_length)

    def classify_intent(self, message: str) -> dict:
        """Classify the intent of a message."""
        response = self.ask(message, role="classify", max_tokens=50)

        intent = "UNKNOWN"
        for category in ["COMMAND", "QUESTION", "ALERT", "STATUS_REQUEST", "GREETING"]:
            if category in response.upper():
                intent = category
                break

        return {"intent": intent, "raw": response}

    def get_status(self) -> dict:
        """Get AI engine status."""
        return {
            "model_loaded": self._model_name,
            "models_available": {
                name: (MODELS_DIR / info["filename"]).exists()
                for name, info in MODEL_REGISTRY.items()
            },
            "stats": self._stats,
            "cache_entries": len(self._cache.cache.get("entries", {})),
        }

    def get_health(self) -> dict:
        """Quick health check — is the AI operational?"""
        # Check Ollama first
        if self._ollama.is_available():
            models = self._ollama.list_models()
            return {
                "status": "operational",
                "backend": "ollama",
                "models": models,
                "queries_served": self._stats["total_queries"],
            }

        # Check llama-cpp
        if self._llm is not None:
            return {
                "status": "operational",
                "backend": "llamacpp",
                "model": self._model_name,
                "queries_served": self._stats["total_queries"],
            }

        if self.is_model_available():
            return {"status": "available", "backend": "llamacpp",
                    "note": "GGUF model exists but not loaded. Ollama not running."}
        return {"status": "no_backend",
                "note": "No AI backend available. Start Ollama or download a GGUF model."}

class OfflineAI:
    """
    Simplified interface for use by other Rudy modules during offline operation.

    Automatically selects the best available model and falls back gracefully.
    """

    _instance = None

    @classmethod
    def get(cls) -> 'OfflineAI':
        """Singleton — one AI instance shared across all modules."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.ai = LocalAI()
        self._loaded = False

    def ensure_ready(self) -> bool:
        """Ensure a model is loaded. Try phi3-mini first (faster), then others."""
        if self._loaded:
            return True

        for model in ["phi3-mini", "tinyllama", "mistral-7b"]:
            if self.ai.is_model_available(model):
                if self.ai.load_model(model):
                    self._loaded = True
                    return True
        return False

    def ask(self, prompt: str, role: str = "general") -> Optional[str]:
        """Ask a question. Returns None if no model available."""
        if not self.ensure_ready():
            return None
        try:
            return self.ai.ask(prompt, role=role)
        except Exception:
            return None

    def should_restart(self, service_name: str, down_minutes: int) -> bool:
        """Quick decision: should we restart this service?"""
        if not self.ensure_ready():
            # Fallback: simple heuristic
            return down_minutes >= 5

        result = self.ai.ops_decision(
            f"Service '{service_name}' has been down for {down_minutes} minutes. "
            f"Should we restart it automatically?"
        )
        return result.get("action") in ["restart_service", "escalate"]

    def triage(self, alert_text: str) -> dict:
        """Quick triage. Falls back to severity 3 if AI unavailable."""
        if not self.ensure_ready():
            return {"severity": 3, "action": "log", "summary": alert_text[:100]}
        return self.ai.triage_alert(alert_text)

if __name__ == "__main__":
    ai = LocalAI()
    print("Local AI Engine (dual backend)")
    print(f"  Models directory: {MODELS_DIR}")

    # Ollama status
    ollama = OllamaBackend()
    if ollama.is_available():
        models = ollama.list_models()
        print(f"\n  Ollama: RUNNING ({len(models)} models)")
        for m in models:
            print(f"    - {m}")
    else:
        print("\n  Ollama: NOT RUNNING (start with 'ollama serve')")

    # GGUF models
    print("\n  GGUF models (llama-cpp fallback):")
    for m in ai.list_available_models():
        status = "DOWNLOADED" if m["available_locally"] else "needs download"
        print(f"    {m['name']:15s} {m['size_gb']}GB  [{status}]  {m['description']}")

    print(f"\n  Health: {json.dumps(ai.get_health(), indent=2)}")
    print("\n  Usage:")
    print("    ai = LocalAI()")
    print("    ai.ask('What is your purpose?')   # Auto-selects Ollama or llama-cpp")
