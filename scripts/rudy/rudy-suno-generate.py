"""
Rudy Suno Quick Generate — Drop-in script for the command runner.
Place in rudy-commands/ to trigger a music generation from Cowork.

Edit the PROMPT and options below, then the command runner will execute it
and write results to rudy-suno-generate.py.result

Example usage via command runner:
    Cowork writes this file to C:\\Users\\C\\Desktop\\rudy-commands\\suno-generate.py
    Command runner executes it
    Result appears in suno-generate.py.result
"""
import sys
import json
sys.path.insert(0, r"C:\Users\C\Desktop")

# ---- EDIT THESE ----
PROMPT = "A cheerful birthday song for a 5 year old"
LYRICS = None          # Set to string for custom lyrics, or None for AI-generated
INSTRUMENTAL = False   # True for no vocals
# --------------------

try:
    from rudy_suno import SunoClient, load_config

    config = load_config()
    client = SunoClient(config)

    if not client.is_configured():
        print(json.dumps({"error": "Suno not configured. Run: python rudy-suno.py setup"}))
        sys.exit(1)

    print(f"Generating: {PROMPT}")
    result = client.generate(
        prompt=PROMPT,
        lyrics=LYRICS,
        instrumental=INSTRUMENTAL,
        wait=True
    )
    print(json.dumps(result, indent=2))

except ImportError:
    print(json.dumps({"error": "rudy-suno.py not found. Make sure it's on the Desktop."}))
except Exception as e:
    print(json.dumps({"error": str(e)}))
