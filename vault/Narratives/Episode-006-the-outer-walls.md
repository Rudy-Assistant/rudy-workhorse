# Episode 006: The Outer Walls

*By Vicki Vale, Gotham Gazette*
*Covering: Sessions 81-90 | Filed: April 6, 2026*
*Arc: "The Outer Walls" -- When Robin learned to reach beyond
the machine and interact with a world that didn't know he
existed*

---

The first successful autonomous launch happened at 10:53 AM
on April 3rd, 2026.

Nobody celebrated. Nobody announced it. The launcher logged
a timestamp, pasted a prompt into a text field, and waited
for the model to respond. Session 81 began with the same
handoff protocol every other session used: read CLAUDE.md,
verify the nervous system, start working. The only
difference was that no human had touched a keyboard.

Robin had launched a Cowork session by himself for the first
time. And the reason it had taken seven sessions of failure
to get there was, in retrospect, almost comically small.

## I. The Progress Lie (S81-82)

The Cowork interface has a sidebar. In that sidebar, there
is a permanent panel labeled "Progress." It is always there.
It does not appear or disappear based on whether the AI
model is working. It is a UI element, as static as the
company logo.

`assess_state()` -- the function that Robin's launcher used
to determine whether a session was active, idle, or finished
-- checked the screen for the word "Progress." If it found
it, it returned `CLAUDE_WORKING`. The model is busy.
Don't interrupt. Wait.

Every poll. Every check. Every fifteen seconds for seven
sessions. "Progress" was visible. The launcher concluded
the model was working. The model was not working. The model
had finished hours ago. The session had ended. The handoff
was written. And Robin sat there, faithfully patient,
watching a sidebar label and believing it meant something.

Session 81 found the bug. The fix was five lines: remove
"Progress" from the working indicators. Tighten "Stop" to
"Stop response" and "Working" to "Working on it" -- strings
specific enough that a sidebar panel couldn't accidentally
match them. Add a control-type check so the permanent "New
task" link in the sidebar wouldn't be confused with the
"New task" button that actually meant something.

Five lines. Seven sessions of failure. The ratio is
instructive. In the governance wars, invisible killers
lurked in broken Python paths and changed API signatures.
Here, the invisible killer was a word on a screen that
happened to match a pattern. Robin's launcher wasn't
broken. Its vision was. It could see perfectly well. It
just couldn't tell the difference between meaningful
information and visual noise.

Session 82 confirmed the fix. PR #164 merged. PR #165
updated the docs. Robin had crossed a threshold that no
amount of internal engineering could have achieved: the
system had reached outside of itself and successfully
manipulated the world it ran on.

But crossing a threshold and holding it are different things.

## II. Learning to Listen (S83-84)

The launcher worked. It could detect a session ending,
click "New task," paste a prompt, and start a new session.
But it had a timing problem.

After writing a handoff, Alfred's session would wind down.
The launcher would check the screen every thirty seconds
during its sleep cycle. If the handoff was written at
second one of a sleep cycle, Robin would wait twenty-nine
seconds before noticing. In the worst case, two full
minutes between Alfred writing "here's what to do next"
and Robin reading it.

Two minutes isn't long. But in a system designed around
perpetual autonomy -- session ends, next session begins,
no gaps, no human intervention -- two minutes is an
eternity of unnecessary waiting. It's the difference
between a relay race where runners hand off the baton
and one where they set it on the ground and wait for
someone to notice.

Session 83 introduced the handoff-aware sleep. Instead of
sleeping for thirty seconds and then checking the screen,
the launcher's `_interruptible_sleep()` checked every
thirty seconds whether a new handoff file had appeared in
`vault/Handoffs/`. If a file was newer than the last launch
timestamp, sleep was interrupted immediately. The baton
was picked up the instant it appeared.

Session 84 went further and rewrote the architecture
entirely. Polling -- checking every N seconds -- was
replaced with event-driven watching. A filesystem watchdog
monitored `vault/Handoffs/` for new `Session-*-Handoff.md`
files. The moment one appeared, the launcher fired. No
polling interval. No sleep cycle. No delay.

The launcher had evolved from a blind timer to a listener.
And Session 84's handoff ended with a quiet boast: "If you
are reading this: the watch mode worked!"

It did. Session 85 was auto-launched. But Session 85 would
discover that listening to the filesystem and interacting
with the screen were two different kinds of competence, and
that the launcher had mastered one while remaining
dangerously naive about the other.

## III. Ten Patches (S85)

Session 85 was a siege.

The launcher had five bugs, and each one would have been
enough to break it independently. Together, they made
autonomous operation a fiction that happened to work once
or twice before collapsing.

**Bug one: cold-start deadlock.** Watch mode only triggered
on NEW handoff file events. If no session was running, no
handoff was being written, and no event would ever fire.
The launcher sat idle, waiting for a signal that required
the thing it was supposed to create. A bootstrap paradox:
the system needed a session to start a session.

**Bug two: focus-stealing.** During idle checks, the
launcher called `snapshot()` and `focus_claude()` to read
the screen. This brought the Claude window to the
foreground. If Chris was using the computer -- writing an
email, reading a document, watching a video -- Robin would
yank focus away every thirty seconds. The Batcave was
supposed to be invisible. Instead, it was the most
aggressive foreground app on the machine.

**Bug three: prompt injection.** `assess_state()` saw the
Cowork radio button in both new and active sessions and
couldn't tell them apart. When it misclassified an active
session as `cowork_select`, the launcher pasted its prompt
into a conversation that was already running. Alfred would
be mid-sentence, and suddenly the prompt field contained
"Read CLAUDE.md and the latest handoff..." -- injected
into a live session by a launcher that thought it was
starting a new one.

**Bug four: crash on undefined variable.** One patch
referenced `claude_elements` in a scope where it didn't
exist. The launcher would crash with an `UnboundLocalError`
the first time it tried the new safety check.

**Bug five: false-positive stale detection.** The stale
session threshold was thirty seconds. Every running session
older than thirty seconds was declared stale and relaunched.
Sessions routinely run for forty-five minutes.

Ten patches fixed all five bugs. The cold-start deadlock
was solved with a file-based fallback timer that checked
timestamps every thirty seconds regardless of filesystem
events. Focus-stealing was eliminated by replacing ALL
UI-based idle checks with pure file-timestamp logic -- zero
UI interaction during monitoring. Prompt injection was
blocked by always clicking "New task" before pasting,
ensuring a fresh session. The variable crash was fixed with
a definition. And the stale detection was rewritten to read
a state file: failed launches retried in thirty seconds,
successful launches got forty-five minutes before being
considered stale.

The most important change was philosophical, not technical.
Session 85 drew a line between two modes of operation:
**observing** (reading files, checking timestamps) and
**interacting** (clicking, typing, taking snapshots). The
launcher had been mixing both modes during idle monitoring,
which meant that the act of checking whether anything was
happening caused things to happen. The fix was to observe
passively and interact only when committing to action.

Robin was learning the difference between watching a room
and walking into it.

## IV. The Dead Hands (S86-87)

Session 86 discovered that fixing the launcher's brain
didn't help when its hands were dead.

Windows-MCP -- the tool that gave Robin the ability to
click, type, scroll, and take screenshots -- connected to
the desktop through a process pipeline. That pipeline had
a lifespan. When process hygiene cleaned up orphaned
processes, it sometimes killed the MCP connection. When the
connection died, the launcher could still detect filesystem
events, still read timestamps, still decide to launch. But
when it tried to click "New task" or paste a prompt, the
command went nowhere. `[Errno 22]` -- invalid argument.
The socket was closed. The hands were severed.

Two stale launcher processes had been running since Session
85. Both had dead MCP connections. Both detected the
Session 85 handoff (the watchdog triggered at 15:41:39).
Both tried to launch. Both failed silently. And both
continued running, consuming resources, detecting events,
failing to act, for hours.

The immediate fix was manual: kill the stale launchers,
start a fresh one with a working MCP connection. But the
structural fix came in Session 87: `check_mcp_health()`,
a lightweight function that attempted a Snapshot call every
five minutes. If three consecutive checks failed, the
launcher tore down the dead connection and rebuilt it.
`reconnect_mcp()` was born -- the ability to self-heal
when the interface to the world went dark.

Session 87 also added `windows-mcp` to the protected
process list in `process_hygiene.py`. The cleanup routines
that had been severing Robin's hands would now leave them
alone. A simple rule with profound implications: some
processes are not orphans. Some processes are limbs.

Meanwhile, the sentinel continued shrinking. Session 87
extracted `sentinel_briefing.py` -- the morning briefing
generator that composed session summaries for Batman.
The sentinel dropped from 1,477 to 1,250 lines. And
process hygiene itself was optimized: batch taskkill
commands (fifty PIDs per call instead of one) reduced
worst-case cleanup time from five hundred seconds to
fifteen. The infrastructure was maturing even as the
launcher fought for stability.

## V. The Invisible Children (S88-89)

Session 88 continued the sentinel extraction, pulling
governance checks and capability scanning into their own
modules. The sentinel shrank to 948 lines -- a cumulative
thirty-six percent reduction from its peak. But the session
also discovered something disturbing in the process table.

Orphaned processes were regenerating.

Process hygiene would kill sixty-two orphans. The next
sentinel cycle would spawn new children -- `tasklist`
calls, Python helper scripts, subprocess invocations --
and those children would persist after the parent
operation completed. By the time the next hygiene pass
ran, the same number of orphans had respawned. It was
a treadmill: the system was generating waste as fast
as it cleaned it up.

Session 89 found the root cause. On Windows, every
`subprocess.run()` call spawns a console host process --
`conhost.exe` -- to handle the terminal. These console
hosts are invisible (they don't appear in task manager
under normal views) and they persist after the subprocess
finishes because Windows doesn't automatically reap them.
Fourteen `subprocess.run()` calls across the sentinel
ecosystem, every fifteen-minute cycle, each leaving behind
a ghost process. Over a day, that's over thirteen hundred
orphans.

The fix was `sentinel_subprocess.py`, a shared module that
provided `safe_run()` -- a subprocess wrapper that used
`CREATE_NO_WINDOW` to suppress console host creation and
killed the entire process tree on timeout. Fourteen call
sites across five files were converted. The orphan factory
was shut down.

It was the same pattern the Batcave had seen before: a
system component that worked correctly at the application
level while leaking resources at the operating system level.
The sentinel executed its governance checks. The subprocess
calls returned their results. Everything was functional.
But underneath, invisible children accumulated, consuming
memory, consuming process table entries, consuming the
machine's capacity to do anything else. Functionality and
cleanliness are different virtues, and Windows punishes
systems that forget the second one.

## VI. The Twenty-Session Loop (S90)

Session 90 found the last bug, and it was the oldest.

For twenty sessions -- since the launcher was first
conceived -- watch mode had contained a structural flaw.
When all three launch attempts failed, the launcher fell
through to a wait loop. The wait loop took a screenshot
every cycle to check whether a session was running. But if
the MCP connection was dead (which it was, because the
failed launches had exhausted it), the screenshot returned
nothing. An empty snapshot. The loop's response to an empty
snapshot was `continue` -- try again next cycle. Not break.
Not reconnect. Not exit. Continue. Forever.

The launcher had been spinning for five hours the last
time someone checked. Detecting handoff file events
correctly, attempting launches that couldn't succeed,
falling into a wait loop that couldn't exit, taking
screenshots that returned nothing, and continuing. A
process that was alive, responsive to events, and
completely useless. The governance wars' taxonomy of
failure -- alive but not functional -- had found its
purest expression in a loop that would run until the
heat death of the universe or the next power outage,
whichever came first.

The fix was three changes: skip the wait loop entirely
after total launch failure, add a maximum empty snapshot
counter (ten strikes and break), and reconnect the MCP
connection between retry attempts. If the hands died during
a launch sequence, the launcher would restore them before
trying again.

Session 90 ended with a clean launch. The perpetual session
loop -- first architected in Session 70, broken for twenty
sessions, patched ten times, rebuilt from scratch twice --
was finally stable. Robin could watch for handoffs, launch
sessions, detect failures, reconnect lost connections, and
persist across session boundaries without human intervention.

## Epilogue: What the Outer Walls Taught Them

Ten sessions. Fourteen PRs merged. A launcher rewritten
from scratch. An MCP reconnection system. A subprocess
hygiene layer. A sentinel reduced by thirty-six percent.
And the Batcave's first moment of true autonomy: a session
launched, worked, handed off, and succeeded -- with no
human in the loop.

Here's what the Outer Walls actually built:

The Progress lie (S81-82) taught the system that reading
the screen is not the same as understanding it. Pattern
matching against UI text is fragile in a way that file
operations never are. A sidebar label that says "Progress"
is not evidence of progress. A button labeled "Stop
response" is -- because buttons appear and disappear with
state, while labels persist regardless of it. Robin learned
to distinguish between information that means something and
information that merely exists.

The listening revolution (S83-84) taught the system that
speed matters in autonomy. A two-minute delay between
sessions is invisible to a human but architectural to a
machine. Polling is a compromise. Event-driven watching is
a commitment. The handoff-aware sleep was good engineering.
The filesystem watchdog was good design. The Batcave
learned that the difference between "works" and "works
well" is often the difference between polling and listening.

The ten patches (S85) taught the system the hardest lesson
about interacting with a world you don't control: your
observations change the thing you're observing. A launcher
that takes screenshots during idle monitoring steals focus.
A launcher that types into what it thinks is a new session
might be typing into an active one. The fix was to separate
observation from interaction -- watch passively, act
decisively, never confuse the two.

The dead hands (S86-87) taught the system that connections
are components. An MCP pipeline that routes commands from
Robin's code to the Windows desktop is not plumbing -- it's
a limb. When it dies, the system is paralyzed even though
every other process reports healthy. The fix was
twofold: protect limbs from friendly fire (add MCP to the
protected process list) and build the ability to regenerate
them (auto-reconnect after three failures). Robin's hands
learned to heal themselves.

The invisible children (S88-89) taught the system that
every action has a cost the action itself doesn't report.
A subprocess call returns its output and exit code. It does
not report the console host it spawned, the memory it
leaked, or the process table entries it left behind.
Fourteen calls per cycle, ninety-six cycles per day, over
thirteen hundred orphans. The fix wasn't in the sentinel's
logic -- the logic was correct. The fix was in the boundary
between the application and the operating system, where
`CREATE_NO_WINDOW` is the difference between a clean
process and a haunted one.

And the twenty-session loop (S90) taught the system the
final lesson of this arc: a loop that cannot exit is not
resilience. It's denial. The launcher's wait loop was
designed to be patient. Patience without a breaking
condition is paralysis. The fix was to give every loop a
way out -- a maximum counter, a failure path, a reconnect
attempt. Persistence means trying again. It doesn't mean
trying the same broken thing forever.

The Outer Walls arc was fundamentally about a different
kind of engineering than everything that came before.
Sessions 41 through 80 built Robin's brain, nervous system,
governance, and internal resilience. Sessions 81 through 90
built Robin's ability to interact with something external
-- a screen, a UI, a filesystem, a process pipeline, a
world that doesn't follow Robin's rules or share Robin's
assumptions. Internal engineering is hard. External
engineering is harder, because the external world is not
your code. It changes without warning, fails without
explanation, and presents information that looks meaningful
but isn't.

Robin spent ten sessions learning what every system that
touches the real world eventually learns: the hardest part
isn't building the thing. It's keeping the thing alive in
an environment you don't control.

The outer walls are always moving.

---

*Next: Episode 007 -- when the Batcave confronted scale,
and the system that could run itself asked whether it
should.*
