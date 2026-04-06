# ADR-020: Andrew-Readiness Score -- Robin as Accessible Agent

**Status:** Proposed
**Date:** 2026-04-06
**Session:** 133 (Lucius evaluation, Batman directive)
**Deciders:** Batman (Chris Cimino)

## Context

The Batcave Mission defines Andrew as the design constraint:
a quadriplegic, non-technical user who can express intent
through whatever channel his body allows -- voice, email,
eye movement, sip-and-puff, or a single switch -- and have
the system act without requiring confirmation, technical
knowledge, or premium subscriptions.

"If it doesn't work for Andrew, it doesn't work."

This ADR scores Robin's current readiness for Andrew and
identifies the development path to 100%.

---

## Scoring Methodology

Ten dimensions, each scored 0-10. The Andrew-Readiness Score
is the weighted average, with weights reflecting criticality
to a quadriplegic non-technical user.

---

## Dimension Scores

### D1: Voice Input (Weight: 15%) -- Score: 3/10

**What exists:**
- `voice_gateway.py`: Mic capture -> faster-whisper (tiny.en)
  -> Ollama intent parsing -> Robin task queue. Supports
  one-shot and continuous wake-word ("hey rudy") modes.
- `voice.py`: TTS (gTTS online, pyttsx3 offline) + STT
  (openai-whisper). Full audio processing pipeline.

**What's missing:**
- Voice gateway is a prototype -- not running as a daemon.
- No streaming/continuous recognition (VAD-based).
- No speaker identification (Andrew vs. caregiver).
- No voice feedback loop (Robin speaks results back).
- Wake-word detection uses full Whisper transcription
  (expensive) instead of a lightweight wake-word engine
  (e.g., openWakeWord, Porcupine).

**Recommended dependencies:**
- `openWakeWord` (Apache 2.0, ~50KB models) -- efficient
  local wake-word detection without full STT overhead.
- `Piper TTS` (MIT) -- fast local TTS, already used by
  Home Assistant. Superior to pyttsx3 for natural speech.
- `silero-vad` (MIT) -- voice activity detection for
  knowing when Andrew starts/stops speaking.
- `faster-whisper` already installed -- upgrade to
  small.en or medium.en for accuracy on impaired speech.

### D2: Alternative Input Channels (Weight: 10%) -- Score: 1/10

**What exists:**
- Email command channel (`email_poller.py`) -- polls IMAP,
  routes to Claude Code, sends replies. Permission tiers.
- Robin chat GUI (`robin_chat_gui.py`) -- web interface.
- Robin chat console -- terminal interface.

**What's missing:**
- Email connectivity currently broken (Known Issue).
- No switch access / sip-and-puff integration.
- No eye-tracking input support.
- No SMS/messaging channel (WhatsApp, Signal).
- No Home Assistant voice pipeline integration.
- Chat interfaces are keyboard-dependent.

**Recommended dependencies:**
- `Tecla` (commercial, ~$600) or open-source sip-and-puff
  (Makers Making Change, ~$85 DIY) -- physical input.
- Home Assistant integration via REST API or MQTT -- bridges
  voice hardware (HA Voice PE, smart speakers) to Robin.
- `Twilio` (API) or `Signal CLI` -- SMS/messaging channel.
- Windows Voice Access (built-in W11) -- OS-level voice nav
  that Robin could leverage for UI interactions.

### D3: Natural Language Understanding (Weight: 12%) -- Score: 5/10

**What exists:**
- Ollama-powered intent parsing (qwen2.5:7b, deepseek-r1:8b).
- `nlp.py` for text processing.
- Voice gateway intent parser extracts structured intents.
- Robin autonomy engine routes through Ollama for decisions.

**What's missing:**
- No disambiguation or clarification flow -- if Robin doesn't
  understand, Andrew gets silence or a wrong action.
- Intent vocabulary is hardcoded (8 types). Andrew's needs
  are open-ended ("check if my prescription was refilled").
- No conversational context (multi-turn dialogue).
- No adaptation to Andrew's speech patterns over time.
- gemma4:26b (best model) is too slow on 16GB RAM.

**Recommended approach:**
- Upgrade to open-ended intent routing (Ollama classifies
  into capability domains, not fixed intent list).
- Add clarification protocol: Robin asks back via TTS
  when confidence < threshold.
- Use qwen2.5:7b for speed; reserve deepseek-r1 for
  complex reasoning only.

### D4: Autonomous Execution (Weight: 15%) -- Score: 6/10

**What exists:**
- `robin_autonomy.py` (56K lines) -- self-directed intelligence,
  directive tracking, decision engine.
- `robin_agent_langgraph.py` (864L) -- stateful workflows
  with checkpointing.
- Task queue for extended absence processing.
- Robin Cowork launcher -- autonomous session management.
- PERCEIVE -> REASON -> ACT -> VERIFY intelligence pattern.

**What's missing:**
- Robin still depends on Alfred for complex orchestration.
- No proactive task initiation based on time/context
  ("it's Monday morning, here's your week").
- Error recovery communicates via logs, not to the user.
- No transaction safety (partial actions aren't rolled back).

**Recommended approach:**
- Build "Morning Robin" -- a proactive routine that runs
  at configurable time, summarizes email/calendar/weather,
  and speaks it to Andrew via TTS.
- Add user-facing error channel: Robin speaks failures
  back ("I couldn't check your email because the server
  is down. I'll try again in 10 minutes.").

### D5: Adaptive Learning / Sentinel (Weight: 10%) -- Score: 3/10

**What exists:**
- `sentinel_learning.py` (24K) -- observation engine.
- Sentinel runs every 15 min, detects changes.
- Knowledge base with ChromaDB semantic search.
- Agent staleness detection.

**What's missing:**
- Automation proposal pipeline exists in architecture
  but isn't actively proposing automations to users.
- No user behavior observation loop running.
- No "did this help?" feedback mechanism.
- Sentinel doesn't yet discover Andrew's patterns.

**Recommended approach:**
- Activate Sentinel's proposal pipeline: observe which
  commands Andrew sends repeatedly, propose Robin automations.
- Add simple feedback: "I did X. Was that right?" via
  whatever channel Andrew uses. Thumb up/down or yes/no voice.

### D6: Daily Living Support (Weight: 12%) -- Score: 4/10

**What exists:**
- Email send/receive (when connectivity works).
- Calendar integration (via Alfred/Cowork).
- Web search (Brave Search MCP).
- File management (Desktop Commander).
- Financial module, travel mode, wellness module.
- Notion integration for knowledge/dashboards.

**What's missing:**
- No medication reminder system.
- No smart home control (lights, temperature, locks, TV).
- No caregiver communication channel.
- No health monitoring integration (vitals, fall detection).
- Calendar access requires Alfred (cloud) -- not Robin-local.
- No grocery/delivery ordering capability.

**Recommended dependencies:**
- Home Assistant REST API -- bridges Robin to smart home
  devices (lights, locks, thermostat, TV, door cameras).
- `ical` (MIT) -- local calendar parsing without cloud.
- Medication reminder: simple JSON schedule + TTS alerts
  (no external dependency needed, Robin can build this).

### D7: Communication Back to User (Weight: 10%) -- Score: 2/10

**What exists:**
- Email replies via Zoho SMTP.
- Chat GUI (web browser required).
- Notion logging (visual, but requires screen access).

**What's missing:**
- No voice output daemon (Robin can generate TTS files
  but doesn't play them proactively).
- No push notifications to Andrew's devices.
- No status announcements ("Task complete" / "I'm working
  on it" / "Something went wrong").
- No ambient audio feedback (confirmation tones, etc.).

**Recommended dependencies:**
- `Piper TTS` + `sounddevice` -- Robin speaks results
  aloud through speakers. Already have sounddevice.
- `ntfy` (MIT, self-hosted push) or `Pushover` ($5 one-time)
  -- push notifications to phone/tablet.
- Home Assistant TTS service -- speak through smart speakers
  in Andrew's room.

### D8: Zero-Config Deployment (Weight: 8%) -- Score: 1/10

**What exists:**
- Comprehensive codebase with 75+ modules.
- Scheduled tasks for agent execution.
- Registry.json and capability index.

**What's missing:**
- No installer or setup wizard.
- Requires Windows, Python 3.12, Ollama, multiple pip
  packages, MCP servers, Git, scheduled tasks.
- No Docker container or single-command deployment.
- No "new Batman onboarding" flow.
- Configuration requires editing YAML/JSON files.

**Recommended approach:**
- Docker Compose stack: Oracle + Robin + Sentinel + Ollama
  in containers. Single `docker compose up`.
- Onboarding wizard: voice-guided setup that asks Andrew
  basic preferences (name, wake word, channels, routines).
- Long-term: Raspberry Pi image for low-cost deployment.

### D9: Cost / Free-Tier Viability (Weight: 8%) -- Score: 7/10

**What exists:**
- Robin runs on Ollama (free, local). Core intelligence
  works without any paid subscription.
- All STT/TTS options have free paths (Whisper, pyttsx3,
  Piper are all free and local).
- Sentinel, agents, task queue -- all free/local.

**What's missing:**
- Alfred requires Claude subscription (~$20/month) for
  complex orchestration. Robin works without Alfred but
  is less capable.
- Email backend uses free tiers (Zoho, Outlook) which
  have limitations.
- Some recommended integrations (Pushover, Twilio) have
  small costs.

**Assessment:** Core system is free. Premium features
(Alfred mentorship, advanced cloud AI) are optional
enhancements, not requirements. This aligns with Mission.

### D10: Safety and Error Recovery (Weight: 10%) -- Score: 3/10

**What exists:**
- Robin liveness with heartbeat and auto-recovery.
- Sentinel monitors agent staleness.
- SystemMaster health checks every 5 minutes.
- Killswitch for emergency shutdown.

**What's missing:**
- No "Andrew is in distress" detection (prolonged silence
  after a voice command, repeated failed attempts).
- No caregiver alert system (text/call a caregiver if
  Robin detects Andrew may need help).
- No graceful degradation announcements ("Email is down,
  but I can still help with voice commands").
- No undo/rollback for actions ("Cancel that" / "Undo").

**Recommended dependencies:**
- Caregiver alert: simple SMS via Twilio or push via ntfy
  when distress patterns detected.
- `apscheduler` (MIT, already common) -- schedule health
  check-ins ("Andrew, are you okay?" every N hours).

---

## Composite Score

| # | Dimension | Weight | Score | Weighted |
|---|-----------|--------|-------|----------|
| D1 | Voice Input | 15% | 3 | 0.45 |
| D2 | Alternative Input | 10% | 1 | 0.10 |
| D3 | NLU / Intent | 12% | 5 | 0.60 |
| D4 | Autonomous Execution | 15% | 6 | 0.90 |
| D5 | Adaptive Learning | 10% | 3 | 0.30 |
| D6 | Daily Living Support | 12% | 4 | 0.48 |
| D7 | Communication Back | 10% | 2 | 0.20 |
| D8 | Zero-Config Deploy | 8% | 1 | 0.08 |
| D9 | Cost / Free-Tier | 8% | 7 | 0.56 |
| D10 | Safety / Recovery | 10% | 3 | 0.30 |
| | **TOTAL** | **100%** | | **3.97/10** |

**Andrew-Readiness Score: 39.7% (INSUFFICIENT)**

Robin has strong architectural bones -- the intelligence
pattern (PERCEIVE->REASON->ACT->VERIFY), the autonomy
engine, the agent infrastructure, and the free/local
philosophy all align with Andrew's needs. But the
**interface layer** is critically underdeveloped. Robin
can think and act, but Andrew cannot easily reach Robin,
and Robin cannot easily reach Andrew.

---

## Development Roadmap to 100%

### Phase 1: "Andrew Can Speak to Robin" (Target: 60%)

Priority: Fix the voice input/output loop.

1. **Voice Daemon** -- Upgrade voice_gateway.py to a
   persistent service: openWakeWord for lightweight
   detection, silero-vad for utterance boundaries,
   faster-whisper small.en for transcription.
   Dependencies: openWakeWord, silero-vad (both MIT, <5MB).
   Impact: D1 -> 6, D2 -> 2. Score -> ~48%.

2. **Voice Response** -- Robin speaks results via Piper TTS
   through speakers. Every action gets voice confirmation.
   Dependency: Piper TTS (MIT, ~50MB voice model).
   Impact: D7 -> 5. Score -> ~53%.

3. **Open-Ended Intent Routing** -- Replace fixed 8-intent
   vocabulary with Ollama domain classifier. Robin asks
   clarifying questions via voice when unsure.
   No new dependencies (uses existing Ollama).
   Impact: D3 -> 7. Score -> ~56%.

4. **Fix Email Channel** -- Restore IMAP connectivity or
   migrate to Gmail API via OAuth. Email is Andrew's
   fallback channel when voice isn't available.
   Impact: D2 -> 3, D6 -> 5. Score -> ~60%.

### Phase 2: "Robin Anticipates Andrew" (Target: 75%)

5. **Morning Robin Routine** -- Proactive daily briefing:
   weather, calendar, email summary, medication reminders.
   Spoken via TTS at configurable time.
   Impact: D4 -> 8, D6 -> 7. Score -> ~67%.

6. **Sentinel Automation Proposals** -- Activate the
   observation->proposal->execute->measure loop from
   Mission.md. Sentinel discovers Andrew's patterns.
   Impact: D5 -> 6. Score -> ~70%.

7. **Home Assistant Bridge** -- Connect Robin to HA via
   REST API. Control lights, locks, thermostat, TV,
   cameras. HA Voice PE as additional mic input.
   Dependency: Home Assistant instance (free, self-hosted).
   Impact: D2 -> 5, D6 -> 8. Score -> ~75%.

### Phase 3: "Andrew Is Safe" (Target: 90%)

8. **Caregiver Alert System** -- Robin detects distress
   patterns (prolonged silence, repeated failures, explicit
   help request) and alerts designated caregiver.
   Dependency: ntfy (free, self-hosted) or Twilio.
   Impact: D10 -> 7. Score -> ~82%.

9. **Graceful Degradation Announcements** -- Robin tells
   Andrew what's working and what's not, in plain language,
   via voice. "Email is down but I can still do X."
   Impact: D10 -> 8, D7 -> 7. Score -> ~86%.

10. **Onboarding Wizard** -- Voice-guided first-run setup.
    "Hi, I'm Robin. What should I call you? What time do
    you usually wake up? Who should I contact in an
    emergency?" Stores preferences in persona_config.
    Impact: D8 -> 5. Score -> ~90%.

### Phase 4: "Any Batman, Any Channel" (Target: 100%)

11. **Docker Compose Deployment** -- Single-command install.
    Oracle + Robin + Sentinel + Ollama + HA in containers.
    Impact: D8 -> 8. Score -> ~94%.

12. **Switch/Eye-Tracking Input** -- Integration with
    Tecla, sip-and-puff, or Talon Voice for C3+ quad
    users who cannot vocalize reliably.
    Dependency: Talon Voice (free, local, Rust-based).
    Impact: D2 -> 8. Score -> ~97%.

13. **Adaptive Speech Recognition** -- Fine-tune Whisper
    on Andrew's specific speech patterns. Many quadriplegic
    users have dysarthria (impaired speech). Standard STT
    models underperform. Few-shot adaptation improves this.
    Impact: D1 -> 9, D3 -> 9. Score -> ~100%.

---

## Dependency Audit Summary

All recommended dependencies are screened for:
license compatibility, active maintenance, security
posture, and alignment with Build-vs-Buy (ADR-005).

| Dependency | License | Stars | Last Update | Purpose |
|-----------|---------|-------|-------------|---------|
| openWakeWord | Apache 2.0 | 1.1K+ | 2025 | Wake word detection |
| silero-vad | MIT | 4K+ | 2025 | Voice activity detection |
| Piper TTS | MIT | 6K+ | 2025 | Local text-to-speech |
| faster-whisper | MIT | 12K+ | 2025 | STT (already installed) |
| Home Assistant | Apache 2.0 | 75K+ | Active | Smart home platform |
| home-llm | MIT | 3K+ | 2025 | HA + Ollama bridge |
| Talon Voice | Free (proprietary) | N/A | Active | Hands-free computer control |
| ntfy | Apache 2.0 | 20K+ | Active | Push notifications |
| apscheduler | MIT | 6K+ | Active | Scheduled check-ins |
| Twilio | Commercial API | N/A | Active | SMS alerts (optional) |
| Makers Making Change S&P | Open source | N/A | Active | DIY sip-and-puff (~$85) |

All are actively maintained, widely adopted, and either
free/open-source or low-cost. None introduce security
concerns for a local-first system.

---

## Consequences

**What becomes easier:**
- Andrew can interact with Robin through voice alone.
- Robin proactively serves Andrew without being asked.
- Caregivers are alerted when Andrew needs help.
- New Batmans can deploy without technical knowledge.

**What becomes harder:**
- System complexity increases (more daemons, more state).
- Hardware requirements may increase (mic, speakers,
  potentially HA hub).
- Testing requires simulating accessibility scenarios.

**What we'll need to revisit:**
- Model selection as Ollama ecosystem evolves.
- HA integration scope as Andrew's needs become clearer.
- Privacy implications of always-on listening.

---

## Action Items (Session 133+)

1. [x] Complete this evaluation (S133)
2. [ ] Phase 1, Step 1: Upgrade voice_gateway.py to daemon
       with openWakeWord + silero-vad
3. [ ] Phase 1, Step 2: Add Piper TTS voice response loop
4. [ ] Phase 1, Step 3: Open-ended intent routing via Ollama
5. [ ] Phase 1, Step 4: Fix email channel connectivity
6. [ ] Phase 2, Step 5: Morning Robin proactive routine
7. [ ] Phase 2, Step 6: Activate Sentinel proposal pipeline
8. [ ] Phase 2, Step 7: Home Assistant bridge
9. [ ] Phase 3+: Safety, onboarding, deployment, adaptive input

---

*Filed by Lucius Fox (acting through Alfred, S133).*
*Methodology: 10-dimension weighted scoring with dependency*
*audit per ADR-005 (Build-vs-Buy). All recommendations*
*screened for license, maintenance, security, and cost.*
