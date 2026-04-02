# Robin Capability Manifest

> **MANDATORY READ before writing ANY Robin code.** (HARD RULE — Session 66)
> Failure to consult this manifest before proposing Robin features = automatic rejection.

## Robin's Brain: Reasoning & Intelligence

| Module | What It Does | When To Use |
|--------|-------------|-------------|
| `rudy/local_ai.py` (661L) | Ollama inference (qwen2.5:7b, deepseek-r1:8b) | ANY decision Robin must make |
| `rudy/robin_autonomy.py` (583L) | Self-directed intelligence, directive tracking | Autonomous task execution |
| `rudy/robin_agent.py` (688L) | Robin Agent v1 (DeepSeek reasoning) | Complex multi-step reasoning |
| `rudy/robin_agent_langgraph.py` (864L) | Robin Agent v2 (LangGraph orchestration) | Stateful workflows |

## Robin's Hands: Physical Interaction

| Module | What It Does | When To Use |
|--------|-------------|-------------|
| `rudy/robin_mcp_client.py` (531L) | MCP client — connects to ANY MCP server (Windows-MCP, GitHub, etc.) | ALL tool execution |
| `rudy/robin_human_adapter.py` (155L) | Human simulation for Windows-MCP (bezier mouse, natural typing) | UI interactions |
| `rudy/human_simulation.py` (1332L) | Full browser behavior simulation | Web automation |

## Robin's Eyes: Perception

| Capability | How | Module |
|-----------|-----|--------|
| **Screen reading** | Windows-MCP Snapshot → structured element list with names + coords | `robin_mcp_client.py` |
| **Element finding** | Parse Snapshot output, find elements BY NAME, extract coordinates dynamically | No hardcoding needed |
| **Visual verification** | Snapshot before AND after actions to confirm success | `robin_mcp_client.py` |
| **File system awareness** | Direct file I/O via Desktop Commander MCP | `robin_mcp_client.py` |

## Robin's Voice: Communication

| Module | What It Does |
|--------|-------------|
| `rudy/robin_alfred_protocol.py` (330L) | Robin↔Alfred IPC |
| `rudy/robin_logger.py` (254L) | Robin→Notion logging |
| `rudy/robin_chat_gui.py` (655L) | Web chat interface |

## Robin's Memory: State & Learning

| Module | What It Does |
|--------|-------------|
| `rudy/batcave_memory.py` (259L) | Shared memory across sessions |
| `rudy/knowledge_base.py` (370L) | Semantic search (ChromaDB) |
| Sentinel observation logs | Pattern learning from Batman behavior |

## Robin's Autonomy: Self-Direction

| Module | What It Does |
|--------|-------------|
| `rudy/robin_autonomy.py` (583L) | Decision engine — routes tasks through Ollama |
| `rudy/robin_liveness.py` (340L) | Heartbeat and auto-recovery |
| `rudy/robin_taskqueue.py` (673L) | Extended absence task queue |
| `rudy/agents/sentinel.py` (1109L) | Change detection, inactivity monitoring |

## The Intelligence Pattern

Robin is an INTELLIGENT AGENT, not a macro bot. Every Robin feature MUST follow this pattern:

```
PERCEIVE → REASON → ACT → VERIFY
    ↑                         |
    └─────────────────────────┘
```

1. **PERCEIVE**: Use Snapshot/read_file/sensors to understand current state
2. **REASON**: Feed perception to Ollama — "What am I seeing? What should I do?"
3. **ACT**: Execute the reasoned action via MCP tools
4. **VERIFY**: Perceive again — did it work? If not, REASON about why and retry.

### What This Means In Practice

**WRONG (macro pattern — BANNED):**
```python
click(215, 109)  # hardcoded "New Task" coordinate
type(prompt)     # no verification it landed in the right place
press_enter()    # hope for the best
```

**RIGHT (intelligence pattern — REQUIRED):**
```python
elements = snapshot()                           # PERCEIVE
target = find_element_by_name("New task")       # REASON (parse, locate)
click(target.x, target.y)                       # ACT
elements = snapshot()                           # VERIFY
if not verify_new_task_opened(elements):        # REASON (did it work?)
    recover_and_retry()                         # ACT (adaptive recovery)
```

## Anti-Patterns (BANNED)

1. **Hardcoded coordinates** — NEVER. Use Snapshot → find by name → extract coords.
2. **Rigid step sequences without verification** — NEVER. Snapshot after every action.
3. **No Ollama in the loop** — If Robin isn't THINKING, you're writing a macro, not a feature.
4. **New dependencies for capabilities Robin already has** — Check this manifest FIRST.
5. **Treating Robin as an executor** — Robin DECIDES. Robin REASONS. Robin ADAPTS.
