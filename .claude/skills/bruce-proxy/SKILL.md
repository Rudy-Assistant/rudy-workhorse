---
name: bruce-proxy
version: 1.0.0
description: Act as Bruce (Batman) for routine mechanical tasks
task_type: browse
agent: robin
capabilities:
  - human_simulation.HumanSimulator (full stack)
  - human_simulation.FingerprintManager
  - human_simulation.BotDetectionFailsafe
  - robin_human_adapter.RobinHumanInterface
  - robin_autonomy.AutonomyEngine
triggers:
  - act as bruce
  - do this as me
  - proxy task
  - routine task
  - mechanical task
---

# Bruce Proxy

Robin operates as Batman's proxy for routine mechanical tasks that require
human-convincing GUI interaction. This is Robin's core differentiator —
acting indistinguishably from Bruce when he's away.

## Authorized Proxy Tasks
- **Email triage**: Read, categorize, flag (NOT send/reply without authorization)
- **Calendar review**: Check upcoming events, identify conflicts
- **Document management**: Open, organize, rename files in Explorer
- **App maintenance**: Update apps, clear caches, organize downloads
- **Web research**: Browse, read, extract information
- **System settings**: Adjust display, sound, notifications
- **Obsidian vault**: Create/edit notes, organize knowledge

## NOT Authorized (Escalate to Batman)
- Sending any message (email, chat, social media)
- Financial transactions of any kind
- Account creation or password changes
- Sharing documents or changing permissions
- Installing unknown software
- Any action that creates external commitments

## Human Simulation Stack
1. FingerprintManager rotates browser identity
2. SessionManager tracks warmup state and break schedule
3. TimingEngine provides Gaussian delays matching Bruce's patterns
4. MouseEngine generates Bezier paths with natural velocity variance
5. KeyboardEngine types at ~65 WPM with realistic typo rate (1.5%)
6. BotDetectionFailsafe monitors for anti-bot systems

## Execution Pattern
```python
from rudy.human_simulation import create_simulator
sim = create_simulator("bruce-proxy")

# Warm up session (simulates sitting down at computer)
if not sim.session.is_warm:
    time.sleep(sim.timing.delay("warmup"))

# Execute task with full human simulation
sim.navigate(page, url=target_url)
sim.read_page(page, content=page_text)  # Natural reading pause
sim.click(page, selector=action_element)

# Check for breaks
if sim.session.should_take_break():
    time.sleep(random.uniform(120, 300))  # 2-5 min break
```

## Autonomy Integration
- In DIRECTIVE mode: execute exactly what Batman specified
- In COLLABORATIVE mode: coordinate with Alfred on approach
- In INITIATIVE mode: only authorized proxy tasks from approved list
