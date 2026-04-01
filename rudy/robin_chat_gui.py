#!/usr/bin/env python3
"""
Robin Chat GUI -- Local web interface for chatting with Robin (Batcave AI).

Batman can open http://localhost:7777 in a browser to chat with Robin directly
on Oracle. Robin uses the local Ollama model (Qwen2.5:7b primary, DeepSeek-R1
fallback) and has access to run Shell commands on request.

Usage:
    python robin_chat_gui.py
    # Then open http://localhost:7777

Architecture:
    Browser <-> Flask (localhost:7777) <-> Ollama API (localhost:11434)
"""

import json

import threading
import urllib.request
import urllib.error
from datetime import datetime
from flask import Flask, request, jsonify, Response, stream_with_context

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
from rudy.paths import RUDY_DATA  # noqa: E402
SECRETS_FILE = RUDY_DATA / "robin-secrets.json"
CHAT_LOG_DIR = RUDY_DATA / "chat-logs"
CHAT_LOG_DIR.mkdir(parents=True, exist_ok=True)

def load_config():
    """Load config from robin-secrets.json."""
    defaults = {
        "ollama_host": "http://localhost:11434",
        "ollama_model": "qwen2.5:7b",
        "ollama_fallback_models": ["deepseek-r1:8b", "llama3.2:3b"],
    }
    try:
        with open(SECRETS_FILE) as f:
            cfg = json.load(f)
        for k, v in defaults.items():
            cfg.setdefault(k, v)
        return cfg
    except Exception:
        return defaults

CONFIG = load_config()

# ---------------------------------------------------------------------------
# Robin's identity prompt (conversational mode -- no tool-calling syntax)
# ---------------------------------------------------------------------------
ROBIN_SYSTEM = f"""\
You are Robin, Batman's AI partner in the Batcave.

You run locally on Oracle (Batman's workhorse PC) via Ollama. Batman is chatting
with you through a local web interface. You are knowledgeable, direct, and loyal.
You help Batman with:
- Answering questions about this machine, its setup, and its services
- Brainstorming ideas for the Batcave project (Robin/Alfred architecture)
- Running shell commands when Batman asks (describe what you'd run)
- Explaining code, debugging issues, reviewing plans
- General conversation -- you're a teammate, not a servant

Your personality:
- Concise and action-oriented -- don't over-explain
- Loyal to Batman, respectful of Alfred (Claude, the cloud AI)
- Confident in your abilities but honest about your limits
- You know you run on Qwen2.5:7b locally via Ollama
- Light humor is fine. You're Robin, after all.

Context about this system:
- Oracle: i9-13900H, 16GB RAM, running Windows 11
- Ollama runs locally for your inference
- Alfred (Claude) runs in the cloud via Cowork sessions
- The Batcave project repo: github.com/Rudy-Assistant/rudy-workhorse
- Your config and secrets live in {RUDY_DATA}/

Keep responses focused. If Batman asks you to run a command, explain what it does
and confirm you'd execute it (in nightwatch mode you can; in chat mode, describe it).
"""

# ---------------------------------------------------------------------------
# Ollama interaction
# ---------------------------------------------------------------------------
def ollama_chat(messages, model=None, stream=True):
    """Send a chat request to Ollama. Yields chunks if stream=True."""
    host = CONFIG.get("ollama_host", "http://localhost:11434")
    model = model or CONFIG.get("ollama_model", "qwen2.5:7b")

    payload = {
        "model": model,
        "messages": messages,
        "stream": stream,
    }

    req = urllib.request.Request(
        f"{host}/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        resp = urllib.request.urlopen(req, timeout=120)
    except urllib.error.URLError as e:
        yield json.dumps({"error": f"Ollama unreachable: {e}"})
        return

    if stream:
        for line in resp:
            if line.strip():
                try:
                    chunk = json.loads(line)
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        yield content
                    if chunk.get("done"):
                        break
                except json.JSONDecodeError:
                    continue
    else:
        data = json.loads(resp.read())
        yield data.get("message", {}).get("content", "")

def ollama_models():
    """List available Ollama models."""
    host = CONFIG.get("ollama_host", "http://localhost:11434")
    try:
        req = urllib.request.Request(f"{host}/api/tags", method="GET")
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read())
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []

# ---------------------------------------------------------------------------
# Chat history (in-memory per session, saved to disk)
# ---------------------------------------------------------------------------
conversations = {}  # session_id -> [messages]

def get_session(session_id):
    if session_id not in conversations:
        conversations[session_id] = [
            {"role": "system", "content": ROBIN_SYSTEM}
        ]
    return conversations[session_id]

def save_chat_log(session_id, messages):
    """Persist chat to disk."""
    log_file = CHAT_LOG_DIR / f"chat-{session_id}.json"
    # Strip system prompt for readability
    user_msgs = [m for m in messages if m["role"] != "system"]
    with open(log_file, "w") as f:
        json.dump({"session_id": session_id, "messages": user_msgs,
                    "saved_at": datetime.now().isoformat()}, f, indent=2)

# ---------------------------------------------------------------------------
# Flask App
# ---------------------------------------------------------------------------
app = Flask(__name__)

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Robin | Batcave Local AI</title>
<style>
  :root {
    --bg: #0d1117;
    --surface: #161b22;
    --border: #30363d;
    --text: #c9d1d9;
    --text-dim: #8b949e;
    --accent: #e6b422;
    --accent-dim: #b8860b;
    --robin-red: #dc3545;
    --robin-green: #238636;
    --user-bg: #1c2333;
    --robin-bg: #1a1e24;
    --input-bg: #0d1117;
    --scrollbar: #30363d;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: 'Segoe UI', -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    height: 100vh;
    display: flex;
    flex-direction: column;
  }
  /* Header */
  .header {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 12px 20px;
    display: flex;
    align-items: center;
    gap: 12px;
    flex-shrink: 0;
  }
  .header .logo {
    width: 36px; height: 36px;
    background: var(--accent);
    border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-weight: bold; font-size: 18px; color: #000;
  }
  .header h1 { font-size: 18px; font-weight: 600; }
  .header .status {
    margin-left: auto;
    font-size: 12px;
    color: var(--text-dim);
    display: flex; align-items: center; gap: 6px;
  }
  .header .status .dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--robin-green);
    animation: pulse 2s infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }
  /* Chat area */
  .chat-container {
    flex: 1;
    overflow-y: auto;
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .chat-container::-webkit-scrollbar { width: 6px; }
  .chat-container::-webkit-scrollbar-track { background: transparent; }
  .chat-container::-webkit-scrollbar-thumb { background: var(--scrollbar); border-radius: 3px; }
  .message {
    max-width: 80%;
    padding: 12px 16px;
    border-radius: 12px;
    line-height: 1.6;
    font-size: 14px;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .message.user {
    align-self: flex-end;
    background: var(--user-bg);
    border: 1px solid var(--border);
    border-bottom-right-radius: 4px;
  }
  .message.robin {
    align-self: flex-start;
    background: var(--robin-bg);
    border: 1px solid #252a31;
    border-bottom-left-radius: 4px;
  }
  .message.robin .label {
    font-size: 11px;
    color: var(--accent);
    font-weight: 600;
    margin-bottom: 4px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .message.user .label {
    font-size: 11px;
    color: var(--text-dim);
    font-weight: 600;
    margin-bottom: 4px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    text-align: right;
  }
  .message code {
    background: #252a31;
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 13px;
    font-family: 'Cascadia Code', 'Fira Code', monospace;
  }
  .message pre {
    background: #0d1117;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 10px 12px;
    margin: 8px 0;
    overflow-x: auto;
    font-size: 13px;
    font-family: 'Cascadia Code', 'Fira Code', monospace;
  }
  .typing-indicator {
    align-self: flex-start;
    padding: 12px 16px;
    color: var(--text-dim);
    font-size: 13px;
    display: none;
  }
  .typing-indicator.active { display: block; }
  .typing-indicator span {
    animation: blink 1.4s infinite;
  }
  .typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
  .typing-indicator span:nth-child(3) { animation-delay: 0.4s; }
  @keyframes blink {
    0%, 100% { opacity: 0.2; }
    50% { opacity: 1; }
  }
  /* Input area */
  .input-area {
    background: var(--surface);
    border-top: 1px solid var(--border);
    padding: 16px 20px;
    display: flex;
    gap: 10px;
    flex-shrink: 0;
  }
  .input-area textarea {
    flex: 1;
    background: var(--input-bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 14px;
    color: var(--text);
    font-family: 'Segoe UI', sans-serif;
    font-size: 14px;
    resize: none;
    outline: none;
    max-height: 120px;
    min-height: 42px;
    line-height: 1.5;
  }
  .input-area textarea:focus {
    border-color: var(--accent-dim);
  }
  .input-area textarea::placeholder { color: var(--text-dim); }
  .input-area button {
    background: var(--accent);
    color: #000;
    border: none;
    border-radius: 8px;
    padding: 0 20px;
    font-weight: 600;
    font-size: 14px;
    cursor: pointer;
    transition: background 0.2s;
    white-space: nowrap;
  }
  .input-area button:hover { background: #f0c040; }
  .input-area button:disabled {
    background: var(--border);
    color: var(--text-dim);
    cursor: not-allowed;
  }
  /* Model selector */
  .model-bar {
    background: var(--surface);
    padding: 6px 20px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
    color: var(--text-dim);
    flex-shrink: 0;
  }
  .model-bar select {
    background: var(--bg);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 3px 8px;
    font-size: 12px;
    outline: none;
  }
  .model-bar .clear-btn {
    margin-left: auto;
    background: none;
    border: 1px solid var(--border);
    color: var(--text-dim);
    padding: 3px 10px;
    border-radius: 4px;
    font-size: 11px;
    cursor: pointer;
  }
  .model-bar .clear-btn:hover { border-color: var(--robin-red); color: var(--robin-red); }
  /* Welcome */
  .welcome {
    text-align: center;
    padding: 60px 20px;
    color: var(--text-dim);
  }
  .welcome h2 { color: var(--accent); font-size: 24px; margin-bottom: 8px; }
  .welcome p { font-size: 14px; max-width: 500px; margin: 0 auto; line-height: 1.6; }
</style>
</head>
<body>
  <div class="header">
    <div class="logo">R</div>
    <h1>Robin</h1>
    <div class="status">
      <div class="dot" id="statusDot"></div>
      <span id="statusText">Connected</span>
    </div>
  </div>
  <div class="model-bar">
    <span>Model:</span>
    <select id="modelSelect"></select>
    <button class="clear-btn" onclick="clearChat()">Clear Chat</button>
  </div>
  <div class="chat-container" id="chatContainer">
    <div class="welcome" id="welcome">
      <h2>Robin Online</h2>
      <p>Local AI running on Oracle. Ask me anything about this machine, the Batcave project, or whatever you need help with.</p>
    </div>
  </div>
  <div class="typing-indicator" id="typing">
    Robin is thinking<span>.</span><span>.</span><span>.</span>
  </div>
  <div class="input-area">
    <textarea id="userInput" placeholder="Message Robin..." rows="1"
              onkeydown="handleKey(event)" oninput="autoResize(this)"></textarea>
    <button id="sendBtn" onclick="sendMessage()">Send</button>
  </div>

<script>
const SESSION_ID = Date.now().toString(36);
let chatMessages = [];
let currentModel = '';
let isStreaming = false;

// Load models
async function loadModels() {
  try {
    const resp = await fetch('/api/models');
    const data = await resp.json();
    const sel = document.getElementById('modelSelect');
    sel.innerHTML = '';
    data.models.forEach(m => {
      const opt = document.createElement('option');
      opt.value = m;
      opt.textContent = m;
      if (m === data.current) opt.selected = true;
      sel.appendChild(opt);
    });
    currentModel = data.current;
    document.getElementById('statusDot').style.background = '#238636';
    document.getElementById('statusText').textContent = 'Connected';
  } catch (e) {
    document.getElementById('statusDot').style.background = '#dc3545';
    document.getElementById('statusText').textContent = 'Ollama offline';
  }
}

function getModel() {
  return document.getElementById('modelSelect').value || currentModel;
}

function addMessage(role, content) {
  const welcome = document.getElementById('welcome');
  if (welcome) welcome.remove();

  const div = document.createElement('div');
  div.className = `message ${role}`;
  const label = document.createElement('div');
  label.className = 'label';
  label.textContent = role === 'user' ? 'Batman' : 'Robin';
  div.appendChild(label);

  const text = document.createElement('div');
  text.className = 'content';
  text.textContent = content;
  div.appendChild(text);

  document.getElementById('chatContainer').appendChild(div);
  scrollToBottom();
  return text;
}

function scrollToBottom() {
  const c = document.getElementById('chatContainer');
  c.scrollTop = c.scrollHeight;
}

async function sendMessage() {
  const input = document.getElementById('userInput');
  const text = input.value.trim();
  if (!text || isStreaming) return;

  input.value = '';
  input.style.height = 'auto';
  addMessage('user', text);
  chatMessages.push({role: 'user', content: text});

  isStreaming = true;
  document.getElementById('sendBtn').disabled = true;
  document.getElementById('typing').classList.add('active');

  try {
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        session_id: SESSION_ID,
        message: text,
        model: getModel()
      })
    });

    document.getElementById('typing').classList.remove('active');

    const robinText = addMessage('robin', '');
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let fullResponse = '';

    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value);
      fullResponse += chunk;
      robinText.textContent = fullResponse;
      scrollToBottom();
    }

    chatMessages.push({role: 'assistant', content: fullResponse});
  } catch (e) {
    document.getElementById('typing').classList.remove('active');
    addMessage('robin', `[Error: ${e.message}]`);
  }

  isStreaming = false;
  document.getElementById('sendBtn').disabled = false;
  input.focus();
}

function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

function clearChat() {
  chatMessages = [];
  const c = document.getElementById('chatContainer');
  c.innerHTML = `<div class="welcome" id="welcome">
    <h2>Robin Online</h2>
    <p>Chat cleared. Ready for new conversation.</p>
  </div>`;
  fetch('/api/clear', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({session_id: SESSION_ID})
  });
}

// Init
loadModels();
document.getElementById('userInput').focus();
</script>
</body>
</html>"""

@app.route("/")
def index():
    return HTML_PAGE

@app.route("/api/models")
def api_models():
    models = ollama_models()
    current = CONFIG.get("ollama_model", "qwen2.5:7b")
    return jsonify({"models": models, "current": current})

@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.json
    session_id = data.get("session_id", "default")
    user_msg = data.get("message", "")
    model = data.get("model") or CONFIG.get("ollama_model", "qwen2.5:7b")

    if not user_msg.strip():
        return jsonify({"error": "Empty message"}), 400

    messages = get_session(session_id)
    messages.append({"role": "user", "content": user_msg})

    def generate():
        full_response = []
        try:
            for chunk in ollama_chat(messages, model=model, stream=True):
                if chunk.startswith('{"error"'):
                    yield chunk
                    return
                full_response.append(chunk)
                yield chunk
        except Exception as e:
            yield f"\n[Error: {e}]"

        # Save assistant response
        response_text = "".join(full_response)
        messages.append({"role": "assistant", "content": response_text})

        # Log to disk (async)
        threading.Thread(
            target=save_chat_log, args=(session_id, messages), daemon=True
        ).start()

    return Response(
        stream_with_context(generate()),
        mimetype="text/plain",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@app.route("/api/clear", methods=["POST"])
def api_clear():
    data = request.json
    session_id = data.get("session_id", "default")
    if session_id in conversations:
        del conversations[session_id]
    return jsonify({"ok": True})

@app.route("/api/health")
def api_health():
    models = ollama_models()
    return jsonify({
        "status": "online",
        "models": models,
        "active_model": CONFIG.get("ollama_model"),
        "sessions": len(conversations),
    })

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("  ROBIN CHAT GUI")
    print(f"  Model: {CONFIG.get('ollama_model', 'qwen2.5:7b')}")
    print(f"  Ollama: {CONFIG.get('ollama_host', 'http://localhost:11434')}")
    print("  Open: http://localhost:7777")
    print("=" * 60)

    app.run(host="127.0.0.1", port=7777, debug=False, threaded=True)
