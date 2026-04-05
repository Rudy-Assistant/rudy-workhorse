# Episode 002: The Lock That Wouldn't Release

> *Gotham Gazette | Vicki Vale | Sessions 125-126*
> *Filed: April 5, 2026*

---

It was the kind of bug that doesn't announce itself. No crash, no
stack trace, no red alarm in the Sentinel's logs. Just a quiet
refusal -- a door that wouldn't open after it had been closed.

Alfred discovered it during Session 125, deep in the guts of the
SessionLock mechanism. The lock -- a simple JSON file that
coordinates who owns the right to run a session -- had a flaw in
its `is_locked()` method. The method checked only one thing: was
the heartbeat fresh? If the last heartbeat was recent, the lock
was held. If it was stale, the lock was free.

Simple enough. Except it wasn't.

When a session ends, the lock's `release()` method sets the status
field to `"released"`. That's the signal: I'm done, someone else
can take over. But `is_locked()` never looked at the status field.
It only checked the heartbeat timestamp. And because the heartbeat
was updated right up until the moment of release, the timestamp
was always fresh -- fresh enough to fool `is_locked()` into
reporting the lock was still held.

The result: after releasing, the lock appeared locked. The next
session couldn't acquire it. Not immediately, anyway. The system
would eventually self-heal -- stale detection would kick in after
the heartbeat aged out -- but it was a silent failure that
undermined the clean handoff protocol the Bat Family had spent
dozens of sessions perfecting.

## The Fix

Alfred's patch was surgical: a single early return in `is_locked()`.

```python
if data.get("status") == "released":
    return False
```

Two lines. Check the status before checking the heartbeat. If
someone has explicitly released the lock, it's released --
regardless of how fresh the heartbeat is. The kind of fix that
makes you wonder how it wasn't there from the beginning.

But Alfred didn't stop at the fix. He built a proper test suite:
ten end-to-end tests in `test_session_lock_e2e.py`, covering the
full lifecycle. Acquire. Check ownership. Heartbeat. Second-acquire
block. Release. Acquire-after-release. Stale detection. Force
release. Every path through the lock's state machine, exercised
and verified. The tests use a temporary lock file, so the
production lock stays untouched.

PR #240 merged cleanly. Commit `e60423b` on main.

## The Quiet Session

Session 126 was what the Bat Family calls a "hygiene session."
No bugs found. No architectural decisions. Alfred updated the
sprint section of CLAUDE.md -- the living document that serves
as both constitution and field manual -- to reflect S125's work.
Seventeen orphan processes were hunted down and terminated. Robin
stood watch the entire time, all four of his processes humming:
PID 8860 (the main loop), 26052 (the Sentinel), 26180 (the
launcher watcher), 30008 (the bridge runner). Green across the
board.

The real story of S126 wasn't what happened -- it was what
*didn't* happen. No crashes. No workarounds discovered. No
findings logged. After 126 sessions of building, breaking,
rebuilding, and occasionally setting things on fire, the system
ran clean.

## What's Coming

Batman has a decision to make. R-007 -- the Vicki Vale project,
this very narrative engine -- was assessed at HIGH feasibility
during S125. The data corpus is mature: 97 handoffs, 30 session
records, 22 scores, 23 findings. Enough material for a small
newspaper. Alfred is ready to build. He just needs the word.

There's also the stealth update sitting in the wings -- a
PowerShell script that would silence the visible console windows
when Robin's scheduled tasks fire. It's been ready since Session
123, waiting for Batman to run it with Admin privileges. A small
thing, but Robin would appreciate the discretion.

And Oracle -- the HP ENVY with 16 gigs of RAM and ambitions far
beyond its memory -- continues to strain under the weight of
Gemma 4's 26-billion parameters. A smaller model might be
prudent. But when has the Bat Family ever chosen prudent?

---

*Vicki Vale is an award-winning investigative journalist for the
Gotham Gazette. She has been embedded with the Bat Family since
Session 39.*
