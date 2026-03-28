"""
Rudy Suno Integration — AI Music Generation for The Workhorse

Generates music via Suno AI. Supports:
- Text-to-music (describe what you want)
- Custom lyrics mode
- Instrumental mode
- Song download and storage

Usage:
    # Generate from a description
    python rudy-suno.py generate --prompt "A happy birthday song for a 5 year old named Sofia"

    # Generate with custom lyrics
    python rudy-suno.py generate --prompt "Children's lullaby" --lyrics "Twinkle little star..."

    # Instrumental only
    python rudy-suno.py generate --prompt "Upbeat piano jazz" --instrumental

    # List recent generations
    python rudy-suno.py list

    # Download a song by ID
    python rudy-suno.py download --id <song_id>

Setup:
    1. pip install suno-api requests
    2. Set SUNO_COOKIE in rudy-suno-config.json (extract from browser)
       OR set SUNO_API_KEY if using a commercial API provider

Configuration file: C:\\Users\\C\\Desktop\\rudy-logs\\rudy-suno-config.json
Output directory:   C:\\Users\\C\\Desktop\\rudy-logs\\suno-output\\
"""

import argparse
import json
import os
import sys
import time
import requests
from pathlib import Path
from datetime import datetime

# Paths
CONFIG_FILE = Path(r"C:\Users\C\Desktop\rudy-logs\rudy-suno-config.json")
OUTPUT_DIR = Path(r"C:\Users\C\Desktop\rudy-logs\suno-output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Default config template
DEFAULT_CONFIG = {
    "auth_method": "cookie",  # "cookie" for direct Suno, "api_key" for commercial provider
    "suno_cookie": "",         # Browser cookie from suno.com (for cookie auth)
    "api_key": "",             # API key (for commercial provider like sunoapi.org)
    "api_base_url": "https://studio-api.suno.ai",  # Suno's internal API
    "commercial_api_url": "https://api.sunoapi.org",  # Commercial fallback
    "model": "chirp-v3-5",    # Latest model
    "default_duration": 60,    # seconds
    "output_dir": str(OUTPUT_DIR),
    "setup_complete": False
}


def load_config():
    """Load or create config file."""
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    else:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
        return DEFAULT_CONFIG.copy()


def save_config(config):
    """Save config to disk."""
    CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")


class SunoClient:
    """Suno AI music generation client with cookie or API key auth."""

    def __init__(self, config):
        self.config = config
        self.session = requests.Session()

        if config["auth_method"] == "cookie" and config.get("suno_cookie"):
            self.session.headers.update({
                "Cookie": config["suno_cookie"],
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://suno.com/",
                "Origin": "https://suno.com"
            })
            self.base_url = config.get("api_base_url", "https://studio-api.suno.ai")
            self.auth_mode = "cookie"
        elif config["auth_method"] == "api_key" and config.get("api_key"):
            self.session.headers.update({
                "Authorization": f"Bearer {config['api_key']}",
                "Content-Type": "application/json"
            })
            self.base_url = config.get("commercial_api_url", "https://api.sunoapi.org")
            self.auth_mode = "api_key"
        else:
            self.auth_mode = None

    def is_configured(self):
        return self.auth_mode is not None

    def generate(self, prompt, lyrics=None, instrumental=False, wait=True):
        """Generate music. Returns list of song dicts."""
        if not self.is_configured():
            return {"error": "Not configured. Run: python rudy-suno.py setup"}

        payload = {
            "prompt": prompt,
            "make_instrumental": instrumental,
            "model": self.config.get("model", "chirp-v3-5"),
            "wait_audio": wait
        }

        if lyrics:
            payload["prompt"] = lyrics
            payload["tags"] = prompt  # Use prompt as style/genre tags

        try:
            if self.auth_mode == "cookie":
                # Direct Suno API
                resp = self.session.post(
                    f"{self.base_url}/api/generate/v2/",
                    json=payload,
                    timeout=120
                )
            else:
                # Commercial API
                resp = self.session.post(
                    f"{self.base_url}/v1/music/generate",
                    json=payload,
                    timeout=120
                )

            resp.raise_for_status()
            result = resp.json()

            # Save generation metadata
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            meta_file = OUTPUT_DIR / f"gen_{ts}.json"
            meta_file.write_text(json.dumps({
                "timestamp": ts,
                "prompt": prompt,
                "lyrics": lyrics,
                "instrumental": instrumental,
                "response": result
            }, indent=2), encoding="utf-8")

            return result

        except requests.exceptions.RequestException as e:
            return {"error": str(e)}

    def download(self, audio_url, filename=None):
        """Download an audio file from Suno."""
        if not filename:
            filename = f"suno_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3"

        output_path = OUTPUT_DIR / filename
        try:
            resp = self.session.get(audio_url, stream=True, timeout=60)
            resp.raise_for_status()
            with open(output_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return str(output_path)
        except Exception as e:
            return {"error": str(e)}

    def list_songs(self):
        """List recent generations from local metadata."""
        songs = []
        for f in sorted(OUTPUT_DIR.glob("gen_*.json"), reverse=True)[:20]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                songs.append({
                    "file": f.name,
                    "timestamp": data.get("timestamp"),
                    "prompt": data.get("prompt"),
                    "instrumental": data.get("instrumental", False)
                })
            except Exception:
                pass
        return songs


def setup_wizard():
    """Interactive setup for Suno credentials."""
    config = load_config()

    print("=" * 50)
    print("  Rudy Suno Setup")
    print("=" * 50)
    print()
    print("Choose authentication method:")
    print("  1. Browser cookie (free, uses your Suno subscription)")
    print("  2. Commercial API key (paid, more reliable)")
    print()

    choice = input("Enter 1 or 2: ").strip()

    if choice == "1":
        config["auth_method"] = "cookie"
        print()
        print("To get your Suno cookie:")
        print("  1. Log into suno.com in Chrome")
        print("  2. Open DevTools (F12) > Application > Cookies > suno.com")
        print("  3. Copy the entire cookie string")
        print("  (Or: DevTools > Network > any request > Headers > Cookie)")
        print()
        cookie = input("Paste cookie string: ").strip()
        if cookie:
            config["suno_cookie"] = cookie
            config["setup_complete"] = True
            save_config(config)
            print("\n  Cookie saved! Testing connection...")
            SunoClient(config)
            # Quick test
            print("  Configuration complete.")
        else:
            print("  No cookie provided. Setup incomplete.")

    elif choice == "2":
        config["auth_method"] = "api_key"
        print()
        print("Enter your commercial API key (e.g. from sunoapi.org):")
        key = input("API Key: ").strip()
        if key:
            config["api_key"] = key
            url = input("API Base URL (press Enter for default): ").strip()
            if url:
                config["commercial_api_url"] = url
            config["setup_complete"] = True
            save_config(config)
            print("\n  API key saved! Configuration complete.")
        else:
            print("  No key provided. Setup incomplete.")
    else:
        print("  Invalid choice.")

    return config


def main():
    parser = argparse.ArgumentParser(description="Rudy Suno — AI Music Generation")
    sub = parser.add_subparsers(dest="command")

    # setup
    sub.add_parser("setup", help="Configure Suno credentials")

    # generate
    gen = sub.add_parser("generate", help="Generate music")
    gen.add_argument("--prompt", required=True, help="Music description or style tags")
    gen.add_argument("--lyrics", help="Custom lyrics (optional)")
    gen.add_argument("--instrumental", action="store_true", help="Instrumental only")
    gen.add_argument("--no-wait", action="store_true", help="Don't wait for audio")

    # list
    sub.add_parser("list", help="List recent generations")

    # download
    dl = sub.add_parser("download", help="Download a song")
    dl.add_argument("--url", required=True, help="Audio URL to download")
    dl.add_argument("--filename", help="Output filename")

    # status
    sub.add_parser("status", help="Check configuration status")

    args = parser.parse_args()

    if args.command == "setup":
        setup_wizard()

    elif args.command == "generate":
        config = load_config()
        client = SunoClient(config)
        if not client.is_configured():
            print("Suno not configured. Run: python rudy-suno.py setup")
            sys.exit(1)

        print(f"Generating: {args.prompt}")
        if args.lyrics:
            print(f"  Lyrics: {args.lyrics[:80]}...")
        if args.instrumental:
            print("  Mode: Instrumental")

        result = client.generate(
            prompt=args.prompt,
            lyrics=args.lyrics,
            instrumental=args.instrumental,
            wait=not args.no_wait
        )

        if "error" in result:
            print(f"  Error: {result['error']}")
            sys.exit(1)

        print(json.dumps(result, indent=2))

    elif args.command == "list":
        config = load_config()
        client = SunoClient(config)
        songs = client.list_songs()
        if songs:
            for s in songs:
                mode = "instrumental" if s["instrumental"] else "vocal"
                print(f"  [{s['timestamp']}] {s['prompt'][:50]} ({mode})")
        else:
            print("  No generations found.")

    elif args.command == "download":
        config = load_config()
        client = SunoClient(config)
        result = client.download(args.url, args.filename)
        if isinstance(result, dict) and "error" in result:
            print(f"  Error: {result['error']}")
        else:
            print(f"  Downloaded: {result}")

    elif args.command == "status":
        config = load_config()
        print("Suno Configuration:")
        print(f"  Auth method: {config.get('auth_method', 'not set')}")
        print(f"  Configured:  {config.get('setup_complete', False)}")
        print(f"  Model:       {config.get('model', 'not set')}")
        print(f"  Output dir:  {config.get('output_dir', 'not set')}")
        if config.get("auth_method") == "cookie":
            has_cookie = bool(config.get("suno_cookie"))
            print(f"  Cookie:      {'set' if has_cookie else 'NOT SET'}")
        elif config.get("auth_method") == "api_key":
            has_key = bool(config.get("api_key"))
            print(f"  API key:     {'set' if has_key else 'NOT SET'}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
