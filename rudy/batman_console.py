#!/usr/bin/env python3
"""Batman Console v2 -- Enhanced web interface for Batman-Robin direct comms.

Features:
  - Chat with Robin (Ollama local LLM)
  - Robin's Inbox feed, color-coded by sender
  - Live Robin activity stream (bridge-runner log tail)
  - Task delegation to Robin's inbox
  - System status dashboard
  - Robin avatar display
  - All chats logged to rudy-data/chat-logs/

Usage:  python -m rudy.batman_console
URL:    http://localhost:7780

Lucius Gate: LG-049 - No new deps. stdlib + flask (installed).
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rudy.paths import RUDY_DATA, RUDY_LOGS  # noqa: E402

from flask import Flask, request, jsonify, Response  # noqa: E402
from flask import stream_with_context, send_file  # noqa: E402

# ---------------------------------------------------------------------------
# Config & Paths
# ---------------------------------------------------------------------------
SECRETS_FILE = RUDY_DATA / "robin-secrets.json"
CHAT_LOG_DIR = RUDY_DATA / "chat-logs"
CHAT_LOG_DIR.mkdir(parents=True, exist_ok=True)
HEARTBEAT_FILE = RUDY_DATA / "bridge-heartbeat.json"
COORD_DIR = RUDY_DATA / "coordination"
ROBIN_INBOX = RUDY_DATA / "robin-inbox"
ROBIN_INBOX_V2 = RUDY_DATA / "inboxes" / "robin-inbox"
ALFRED_INBOX = RUDY_DATA / "alfred-inbox"
BRIDGE_LOG = RUDY_DATA / "logs" / "bridge-runner.log"
try:
    from rudy.paths import ROBIN_AVATAR
except ImportError:
    ROBIN_AVATAR = RUDY_DATA / "assets" / "robin-avatar.png"
PORT = 7780


def load_config():
    defaults = {
        "ollama_host": "http://localhost:11434",
        "ollama_model": "qwen2.5:7b",
        "ollama_fallback_models": ["deepseek-r1:8b"],
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
# Robin System Prompt
# ---------------------------------------------------------------------------
ROBIN_SYSTEM = (
    "You are Robin, Batman's AI partner in the Batcave. "
    "You run locally on Oracle via Ollama (Qwen2.5:7b). Batman is chatting "
    "with you through the Batman Console. Be concise, direct, loyal. "
    "Help with system management, dev tasks, Batcave ops, brainstorming. "
    "Light humor welcome. You're Robin, after all. "
    f"Data dir: {RUDY_DATA}. Repo: github.com/Rudy-Assistant/rudy-workhorse."
)


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------
def ollama_chat(messages, model=None, stream=True):
    host = CONFIG.get("ollama_host", "http://localhost:11434")
    model = model or CONFIG.get("ollama_model", "qwen2.5:7b")
    payload = {"model": model, "messages": messages, "stream": stream}
    req = urllib.request.Request(
        f"{host}/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=120)  # nosec B310
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


def ollama_available():
    host = CONFIG.get("ollama_host", "http://localhost:11434")
    try:
        with urllib.request.urlopen(  # nosec B310
            urllib.request.Request(f"{host}/api/tags"), timeout=5
        ) as r:
            return r.status == 200
    except Exception:
        return False

# ---------------------------------------------------------------------------
# Chat sessions & logging
# ---------------------------------------------------------------------------
conversations = {}


def get_session(sid):
    if sid not in conversations:
        conversations[sid] = [{"role": "system", "content": ROBIN_SYSTEM}]
    return conversations[sid]


def save_chat_log(sid, messages):
    log_file = CHAT_LOG_DIR / f"batman-{sid}.json"
    user_msgs = [m for m in messages if m["role"] != "system"]
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump({"session_id": sid, "source": "batman-console",
                    "messages": user_msgs,
                    "saved_at": datetime.now().isoformat()}, f, indent=2)


# ---------------------------------------------------------------------------
# Inbox reader (all inboxes, color-coded by sender)
# ---------------------------------------------------------------------------
SENDER_MAP = {
    "alfred": "alfred", "batman": "batman", "lucius": "lucius",
    "sentinel": "oracle", "oracle": "oracle", "nightwatch": "oracle",
    "systemmaster": "oracle", "securityagent": "oracle",
    "vicki": "vicki", "vale": "vicki",
}


def _detect_sender(msg):
    """Determine sender from message metadata."""
    frm = str(msg.get("from", "")).lower()
    for key, val in SENDER_MAP.items():
        if key in frm:
            return val
    # Check payload
    payload = msg.get("payload", {})
    src = str(payload.get("source", "")).lower()
    assigned = str(payload.get("assigned_by", "")).lower()
    for key, val in SENDER_MAP.items():
        if key in src or key in assigned:
            return val
    # Infer from type
    mtype = msg.get("type", "")
    if mtype in ("task", "session_start", "session_end", "finding"):
        return "alfred"
    if mtype in ("report", "escalation", "help_offer", "health"):
        return "robin"
    return "unknown"

def get_inbox_messages(limit=50):
    """Read Robin's inbox messages, sorted newest first."""
    msgs = []
    for inbox in [ROBIN_INBOX, ROBIN_INBOX_V2]:
        if not inbox.exists():
            continue
        for f in inbox.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                data["_file"] = f.name
                data["_sender"] = _detect_sender(data)
                msgs.append(data)
            except Exception:
                pass
    # Also scan alfred-inbox for Robin's outbound messages
    if ALFRED_INBOX.exists():
        for f in sorted(ALFRED_INBOX.glob("*.json"), reverse=True)[:30]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                data["_file"] = f.name
                data["_sender"] = "robin"
                data["_inbox"] = "alfred-inbox"
                msgs.append(data)
            except Exception:
                pass
    # Sort by timestamp descending
    def _ts(m):
        t = m.get("timestamp", m.get("_file", "0"))
        return str(t)
    msgs.sort(key=_ts, reverse=True)
    return msgs[:limit]


# ---------------------------------------------------------------------------
# Task delegation
# ---------------------------------------------------------------------------
def send_task_to_robin(task_description, priority="normal"):
    ts = int(time.time())
    msg = {
        "msg_id": f"batman-console-{ts}",
        "type": "task", "from": "batman",
        "timestamp": datetime.now().isoformat(),
        "priority": priority,
        "payload": {
            "subject": task_description[:100],
            "details": task_description,
            "source": "batman-console",
            "assigned_by": "batman",
        },
    }
    for inbox in [ROBIN_INBOX, ROBIN_INBOX_V2]:
        inbox.mkdir(parents=True, exist_ok=True)
        fpath = inbox / f"{ts}-task.json"
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(msg, f, indent=2)
    return msg["msg_id"]

# ---------------------------------------------------------------------------
# Activity stream (tail bridge-runner.log)
# ---------------------------------------------------------------------------
def get_activity_lines(n=40):
    """Read last N lines from bridge-runner.log."""
    if not BRIDGE_LOG.exists():
        return ["(no bridge log found)"]
    try:
        with open(BRIDGE_LOG, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return [ln.rstrip() for ln in lines[-n:]]
    except Exception as e:
        return [f"(error reading log: {e})"]


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
def get_system_status():
    status = {"ollama": "offline", "bridge": {}, "alfred": {}, "robin": {}}
    if ollama_available():
        status["ollama"] = "online"
    for key, fname in [("bridge", HEARTBEAT_FILE),
                       ("alfred", COORD_DIR / "alfred-status.json"),
                       ("robin", COORD_DIR / "robin-status.json")]:
        try:
            status[key] = json.loads(Path(fname).read_text(encoding="utf-8"))
        except Exception:
            pass
    return status

# ---------------------------------------------------------------------------
# Flask App & Routes
# ---------------------------------------------------------------------------
app = Flask(__name__)


@app.route("/")
def index():
    return HTML_PAGE


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    user_msg = data.get("message", "").strip()
    sid = data.get("session_id", "default")
    if not user_msg:
        return jsonify({"error": "Empty message"}), 400
    messages = get_session(sid)
    messages.append({"role": "user", "content": user_msg})

    def generate():
        full = []
        for chunk in ollama_chat(messages):
            full.append(chunk)
            yield chunk
        messages.append({"role": "assistant", "content": "".join(full)})
        save_chat_log(sid, messages)

    return Response(stream_with_context(generate()), mimetype="text/plain")


@app.route("/api/task", methods=["POST"])
def delegate_task():
    data = request.json
    task = data.get("task", "").strip()
    priority = data.get("priority", "normal")
    if not task:
        return jsonify({"error": "Empty task"}), 400
    msg_id = send_task_to_robin(task, priority)
    return jsonify({"status": "sent", "msg_id": msg_id})


@app.route("/api/status")
def status():
    return jsonify(get_system_status())


@app.route("/api/inbox")
def inbox():
    limit = request.args.get("limit", 50, type=int)
    return jsonify(get_inbox_messages(limit))


@app.route("/api/activity")
def activity():
    n = request.args.get("lines", 40, type=int)
    return jsonify(get_activity_lines(n))


@app.route("/api/avatar")
def avatar():
    if ROBIN_AVATAR.exists():
        return send_file(str(ROBIN_AVATAR), mimetype="image/png")
    # Fallback: 1px transparent
    return Response(b"", mimetype="image/png", status=404)


# ---------------------------------------------------------------------------
# HTML Page (v2 — inbox, activity, avatar)
# ---------------------------------------------------------------------------
HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Batman Console | Robin Direct Line</title>
<style>
:root {
  --bg:#0a0e14; --surface:#121820; --surface2:#1a2030; --border:#252d3a;
  --text:#c8d0dc; --dim:#6b7a8d; --gold:#e6b422; --gold-dim:#b8860b;
  --red:#dc3545; --green:#238636; --blue:#388bfd; --cyan:#56d4ef;
  --purple:#a78bfa; --orange:#f0883e;
  --c-batman:#e6b422; --c-alfred:#56d4ef; --c-lucius:#a78bfa;
  --c-oracle:#f0883e; --c-robin:#238636; --c-vicki:#ec4899; --c-unknown:#6b7a8d;
  --user-bg:#162040; --robin-bg:#141a22; --input-bg:#0d1117;
}
*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:'Segoe UI',-apple-system,sans-serif;background:var(--bg);color:var(--text);height:100vh;display:flex;flex-direction:column;overflow:hidden;}
</style>
"""

HTML_PAGE += """
<style>
/* HEADER */
.header{background:var(--surface);border-bottom:2px solid var(--gold-dim);padding:8px 16px;display:flex;align-items:center;gap:12px;flex-shrink:0;}
.header .avatar{width:42px;height:42px;border-radius:50%;border:2px solid var(--gold);object-fit:cover;}
.header .title h1{font-size:16px;font-weight:700;color:var(--gold);letter-spacing:.5px;}
.header .title .sub{font-size:10px;color:var(--dim);margin-top:1px;}
.header .dots{margin-left:auto;display:flex;gap:14px;font-size:10px;letter-spacing:.3px;}
.header .dots .item{display:flex;align-items:center;gap:4px;color:var(--dim);}
.dot{width:7px;height:7px;border-radius:50%;} .dot.on{background:var(--green);} .dot.off{background:var(--red);}
.dot.pulse{animation:pulse 2s infinite;} @keyframes pulse{0%,100%{opacity:1;}50%{opacity:.3;}}

/* LAYOUT: 3 columns */
.main{display:flex;flex:1;overflow:hidden;}
.col-left{width:280px;background:var(--surface);border-right:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden;}
.col-center{flex:1;display:flex;flex-direction:column;}
.col-right{width:300px;background:var(--surface);border-left:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden;}

/* TABS */
.tab-bar{display:flex;border-bottom:1px solid var(--border);flex-shrink:0;}
.tab-bar button{flex:1;background:none;border:none;color:var(--dim);font-size:10px;padding:7px 4px;cursor:pointer;border-bottom:2px solid transparent;font-weight:600;letter-spacing:.5px;text-transform:uppercase;}
.tab-bar button.active{color:var(--gold);border-bottom-color:var(--gold);}
.tab-bar button:hover{color:var(--text);}
</style>
"""

HTML_PAGE += """
<style>
/* CHAT */
.chat-area{flex:1;overflow-y:auto;padding:14px 18px;display:flex;flex-direction:column;gap:10px;}
.chat-area::-webkit-scrollbar{width:5px;} .chat-area::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px;}
.msg{max-width:80%;padding:10px 14px;border-radius:10px;line-height:1.55;font-size:13px;white-space:pre-wrap;word-break:break-word;}
.msg.user{align-self:flex-end;background:var(--user-bg);border:1px solid var(--border);border-bottom-right-radius:3px;}
.msg.robin{align-self:flex-start;background:var(--robin-bg);border:1px solid #1e2530;border-bottom-left-radius:3px;}
.msg .label{font-size:10px;font-weight:700;margin-bottom:3px;text-transform:uppercase;letter-spacing:.5px;}
.msg.robin .label{color:var(--gold);} .msg.user .label{color:var(--dim);text-align:right;}
.msg code{background:#1e2530;padding:1px 4px;border-radius:3px;font-size:12px;font-family:'Cascadia Code','Fira Code',monospace;}
.msg pre{background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:8px;margin:6px 0;overflow-x:auto;font-size:12px;font-family:'Cascadia Code','Fira Code',monospace;}
.typing{align-self:flex-start;color:var(--dim);font-size:11px;display:none;padding:6px 14px;}

/* INPUT BAR */
.input-bar{background:var(--surface);border-top:1px solid var(--border);padding:10px 14px;display:flex;gap:8px;flex-shrink:0;}
.input-bar textarea{flex:1;background:var(--input-bg);border:1px solid var(--border);border-radius:8px;color:var(--text);padding:9px 12px;font-size:13px;font-family:inherit;resize:none;outline:none;min-height:40px;max-height:110px;}
.input-bar textarea:focus{border-color:var(--gold-dim);}
.input-bar button{background:var(--gold);color:#000;border:none;border-radius:8px;padding:0 16px;font-weight:700;font-size:12px;cursor:pointer;}
.input-bar button:hover{background:var(--gold-dim);} .input-bar button:disabled{opacity:.4;cursor:not-allowed;}
</style>
"""

HTML_PAGE += """
<style>
/* LEFT PANEL: INBOX */
.inbox-feed{flex:1;overflow-y:auto;padding:6px 0;}
.inbox-feed::-webkit-scrollbar{width:4px;} .inbox-feed::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px;}
.inbox-msg{padding:8px 12px;border-bottom:1px solid var(--border);cursor:default;transition:background .15s;}
.inbox-msg:hover{background:var(--surface2);}
.inbox-msg .im-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;}
.inbox-msg .im-sender{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;}
.inbox-msg .im-time{font-size:9px;color:var(--dim);}
.inbox-msg .im-type{font-size:9px;padding:1px 5px;border-radius:3px;background:var(--surface2);color:var(--dim);margin-left:4px;}
.inbox-msg .im-subject{font-size:11px;color:var(--text);line-height:1.4;}
.inbox-msg .im-detail{font-size:10px;color:var(--dim);margin-top:2px;max-height:36px;overflow:hidden;}
/* Sender colors */
.sender-batman{color:var(--c-batman);} .sender-alfred{color:var(--c-alfred);}
.sender-lucius{color:var(--c-lucius);} .sender-oracle{color:var(--c-oracle);}
.sender-robin{color:var(--c-robin);} .sender-vicki{color:var(--c-vicki);}
.sender-unknown{color:var(--c-unknown);}

/* RIGHT PANEL: ACTIVITY + STATUS + TASK */
.activity-feed{flex:1;overflow-y:auto;padding:6px 10px;font-family:'Cascadia Code','Fira Code',monospace;font-size:10px;line-height:1.6;color:var(--dim);background:#0a0d12;}
.activity-feed::-webkit-scrollbar{width:4px;} .activity-feed::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px;}
.activity-feed .al-info{color:var(--cyan);} .activity-feed .al-warn{color:var(--orange);}
.activity-feed .al-error{color:var(--red);} .activity-feed .al-inbox{color:var(--gold);}
.status-section{padding:8px 12px;border-bottom:1px solid var(--border);}
.kv{display:flex;justify-content:space-between;font-size:11px;padding:2px 0;} .kv .k{color:var(--dim);} .kv .v{color:var(--text);font-weight:500;}
.task-form{padding:10px 12px;}
.task-form textarea{width:100%;background:var(--input-bg);border:1px solid var(--border);border-radius:6px;color:var(--text);padding:7px 9px;font-size:11px;font-family:inherit;resize:vertical;min-height:50px;outline:none;}
.task-form textarea:focus{border-color:var(--gold-dim);}
.task-form select{width:100%;background:var(--input-bg);border:1px solid var(--border);border-radius:5px;color:var(--text);padding:5px 7px;font-size:11px;margin-top:5px;outline:none;}
.task-form button{width:100%;background:var(--blue);color:#fff;border:none;border-radius:5px;padding:7px;font-size:11px;font-weight:600;cursor:pointer;margin-top:6px;}
.task-form button:hover{opacity:.85;}
.task-result{font-size:10px;color:var(--green);padding:3px 0;display:none;}
</style>
"""

HTML_PAGE += """
<body>
<!-- HEADER -->
<div class="header">
  <img class="avatar" src="/api/avatar" alt="Robin" onerror="this.style.display='none'">
  <div class="title"><h1>BATMAN CONSOLE</h1><div class="sub">Robin Direct Line &mdash; Oracle Local AI</div></div>
  <div class="dots">
    <div class="item"><span class="dot on pulse" id="dot-ollama"></span> Ollama</div>
    <div class="item"><span class="dot on" id="dot-bridge"></span> Bridge</div>
    <div class="item"><span class="dot on" id="dot-alfred"></span> Alfred</div>
  </div>
</div>

<!-- MAIN 3-COLUMN LAYOUT -->
<div class="main">
  <!-- LEFT: Inbox -->
  <div class="col-left">
    <div class="tab-bar">
      <button class="active" onclick="switchLeft('inbox',this)">Inbox</button>
      <button onclick="switchLeft('logs',this)">Chat Logs</button>
    </div>
    <div id="left-inbox" class="inbox-feed"></div>
    <div id="left-logs" class="inbox-feed" style="display:none;padding:8px 12px;font-size:11px;"></div>
  </div>

  <!-- CENTER: Chat -->
  <div class="col-center">
    <div class="chat-area" id="chatArea">
      <div class="msg robin"><div class="label">Robin</div>Batman Console v2 online. I'm here, sir. Chat on the left, inbox feed on the right, or assign tasks below.</div>
    </div>
    <div class="typing" id="typing">Robin is thinking...</div>
    <div class="input-bar">
      <textarea id="userInput" rows="1" placeholder="Talk to Robin... (Enter to send, Shift+Enter for newline)"></textarea>
      <button id="sendBtn" onclick="sendMessage()">Send</button>
    </div>
  </div>

  <!-- RIGHT: Activity / Status / Tasks -->
  <div class="col-right">
    <div class="tab-bar">
      <button class="active" onclick="switchRight('activity',this)">Activity</button>
      <button onclick="switchRight('status',this)">Status</button>
      <button onclick="switchRight('tasks',this)">Tasks</button>
    </div>
    <div id="right-activity" class="activity-feed"></div>
    <div id="right-status" style="display:none"><div class="status-section" id="statusSection">Loading...</div></div>
    <div id="right-tasks" style="display:none">
      <div class="task-form">
        <textarea id="taskInput" placeholder="Describe the task for Robin..."></textarea>
        <select id="taskPriority"><option value="normal">Normal</option><option value="high">High</option><option value="critical">Critical</option></select>
        <button onclick="sendTask()">Delegate Task</button>
        <div class="task-result" id="taskResult"></div>
      </div>
    </div>
  </div>
</div>
"""

HTML_PAGE += """
<script>
const sessionId = 'bat-' + Date.now().toString(36);
const chatArea = document.getElementById('chatArea');
const userInput = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
const typing = document.getElementById('typing');
let sending = false;

userInput.addEventListener('input', function(){
  this.style.height='auto'; this.style.height=Math.min(this.scrollHeight,110)+'px';
});
userInput.addEventListener('keydown', function(e){
  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage();}
});

function esc(t){
  return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/`([^`]+)`/g,'<code>$1</code>');
}

function addMsg(role, text){
  const d=document.createElement('div'); d.className='msg '+role;
  const label=role==='robin'?'Robin':'Batman';
  d.innerHTML='<div class="label">'+label+'</div>'+esc(text);
  chatArea.appendChild(d); chatArea.scrollTop=chatArea.scrollHeight; return d;
}

async function sendMessage(){
  const text=userInput.value.trim(); if(!text||sending)return;
  sending=true; sendBtn.disabled=true;
  addMsg('user',text); userInput.value=''; userInput.style.height='auto';
  typing.style.display='block'; chatArea.scrollTop=chatArea.scrollHeight;
  try{
    const resp=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text,session_id:sessionId})});
    typing.style.display='none';
    const reader=resp.body.getReader(); const dec=new TextDecoder();
    const msgDiv=addMsg('robin',''); let full='';
    while(true){const{done,value}=await reader.read();if(done)break;full+=dec.decode(value,{stream:true});msgDiv.innerHTML='<div class="label">Robin</div>'+esc(full);chatArea.scrollTop=chatArea.scrollHeight;}
  }catch(err){typing.style.display='none';addMsg('robin','[Error: '+err.message+']');}
  sending=false; sendBtn.disabled=false; userInput.focus();
}
</script>
"""

HTML_PAGE += """
<script>
// --- SENDER COLOR MAP ---
const SENDER_COLORS = {batman:'var(--c-batman)',alfred:'var(--c-alfred)',lucius:'var(--c-lucius)',oracle:'var(--c-oracle)',robin:'var(--c-robin)',vicki:'var(--c-vicki)',unknown:'var(--c-unknown)'};
const SENDER_LABELS = {batman:'Batman',alfred:'Alfred',lucius:'Lucius Fox',oracle:'Oracle/Sentinel',robin:'Robin',vicki:'Vicki Vale',unknown:'Unknown'};

// --- INBOX FEED ---
async function loadInbox(){
  try{
    const resp=await fetch('/api/inbox'); const msgs=await resp.json();
    const el=document.getElementById('left-inbox');
    if(!msgs.length){el.innerHTML='<div style="padding:12px;color:var(--dim);font-size:11px;">No inbox messages.</div>';return;}
    el.innerHTML=msgs.map(m=>{
      const s=m._sender||'unknown';
      const ts=m.timestamp?(m.timestamp.replace('T',' ').slice(0,16)):(m._file||'');
      const mtype=m.type||'?';
      const subj=(m.payload&&m.payload.subject)||mtype;
      const detail=(m.payload&&(m.payload.details||m.payload.what_noticed||''))||'';
      return '<div class="inbox-msg">'
        +'<div class="im-header"><span class="im-sender sender-'+s+'">'+(SENDER_LABELS[s]||s)+'</span><span class="im-type">'+esc(mtype)+'</span><span class="im-time">'+esc(ts)+'</span></div>'
        +'<div class="im-subject">'+esc(subj.slice(0,80))+'</div>'
        +(detail?'<div class="im-detail">'+esc(detail.slice(0,120))+'</div>':'')
        +'</div>';
    }).join('');
  }catch(e){document.getElementById('left-inbox').textContent='Error: '+e.message;}
}

// --- ACTIVITY FEED ---
async function loadActivity(){
  try{
    const resp=await fetch('/api/activity'); const lines=await resp.json();
    const el=document.getElementById('right-activity');
    el.innerHTML=lines.map(ln=>{
      let cls='';
      if(ln.includes('INFO'))cls='al-info';
      else if(ln.includes('WARNING'))cls='al-warn';
      else if(ln.includes('ERROR'))cls='al-error';
      else if(ln.includes('[Inbox]'))cls='al-inbox';
      return '<div class="'+cls+'">'+esc(ln)+'</div>';
    }).join('');
    el.scrollTop=el.scrollHeight;
  }catch(e){document.getElementById('right-activity').textContent='Error: '+e.message;}
}
</script>
"""

HTML_PAGE += """
<script>
// --- STATUS / TASKS / TABS ---
async function refreshStatus(){
  try{
    const resp=await fetch('/api/status'); const s=await resp.json();
    document.getElementById('dot-ollama').className='dot '+(s.ollama==='online'?'on pulse':'off');
    document.getElementById('dot-bridge').className='dot '+((s.bridge&&s.bridge.status==='running')?'on':'off');
    document.getElementById('dot-alfred').className='dot '+((s.alfred&&s.alfred.state==='active')?'on pulse':'off');
    const sec=document.getElementById('statusSection');
    let h='';
    h+='<div class="kv"><span class="k">Ollama</span><span class="v">'+s.ollama+'</span></div>';
    h+='<div class="kv"><span class="k">Bridge PID</span><span class="v">'+(s.bridge.pid||'?')+'</span></div>';
    h+='<div class="kv"><span class="k">Bridge Iters</span><span class="v">'+(s.bridge.iterations||'?')+'</span></div>';
    h+='<div class="kv"><span class="k">Robin</span><span class="v">'+(s.robin.state||'?')+'</span></div>';
    h+='<div class="kv"><span class="k">Alfred</span><span class="v">'+(s.alfred.state||'?')+' (S'+(s.alfred.session_number||'?')+')</span></div>';
    h+='<div class="kv"><span class="k">Detail</span><span class="v" style="font-size:10px;max-width:170px;text-align:right">'+(s.alfred.details||'').slice(0,90)+'</span></div>';
    sec.innerHTML=h;
  }catch(e){document.getElementById('statusSection').textContent='Error';}
}

async function sendTask(){
  const task=document.getElementById('taskInput').value.trim();
  const priority=document.getElementById('taskPriority').value;
  if(!task)return;
  const res=document.getElementById('taskResult');
  try{
    const resp=await fetch('/api/task',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({task,priority})});
    const data=await resp.json();
    res.textContent='Sent: '+data.msg_id; res.style.display='block'; res.style.color='var(--green)';
    document.getElementById('taskInput').value='';
    addMsg('user','[Task delegated] '+task);
    addMsg('robin','Task queued ('+data.msg_id+'). Bridge picks it up next cycle.');
    setTimeout(()=>{res.style.display='none';loadInbox();},3000);
  }catch(err){res.textContent='Error: '+err.message;res.style.display='block';res.style.color='var(--red)';}
}

async function loadLogs(){
  try{
    const resp=await fetch('/api/logs');
    // api/logs doesn't exist yet in v2, reuse chat-log dir listing
    document.getElementById('left-logs').innerHTML='<div style="color:var(--dim)">Chat logs saved to rudy-data/chat-logs/</div>';
  }catch(e){}
}

function switchLeft(name,btn){
  btn.parentElement.querySelectorAll('button').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('left-inbox').style.display=name==='inbox'?'':'none';
  document.getElementById('left-logs').style.display=name==='logs'?'':'none';
  if(name==='inbox')loadInbox();
}
function switchRight(name,btn){
  btn.parentElement.querySelectorAll('button').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  ['activity','status','tasks'].forEach(t=>document.getElementById('right-'+t).style.display=t===name?'':'none');
  if(name==='activity')loadActivity();
  if(name==='status')refreshStatus();
}

// --- INIT ---
refreshStatus(); loadInbox(); loadActivity();
setInterval(refreshStatus,30000);
setInterval(loadInbox,15000);
setInterval(loadActivity,10000);
userInput.focus();
</script>
</body></html>
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Batman Console v2")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    print(f"\n  Batman Console v2 starting on http://{args.host}:{args.port}")
    print(f"  Chat logs: {CHAT_LOG_DIR}")
    print(f"  Robin inbox: {ROBIN_INBOX}")
    print(f"  Avatar: {ROBIN_AVATAR} ({'found' if ROBIN_AVATAR.exists() else 'MISSING'})\n")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
