## Context

Openhoof agents are defined by a workspace directory containing `agent.yaml` (configuration) and identity files (`SOUL.md`, `AGENTS.md`, `MEMORY.md`, etc.). The `AgentConfig` dataclass supports core fields (model, tools, heartbeat) plus advanced sections (autonomy, hot_state, sensors). Creating an agent today requires:

1. Creating the workspace directory under `~/.atmosphere/agents/<agent_id>/`
2. Writing a valid `agent.yaml` with the correct schema
3. Writing a `SOUL.md` that defines the agent's identity and behavior
4. Optionally writing `AGENTS.md`, `TOOLS.md`, `HEARTBEAT.md`, etc.
5. Knowing which tools exist, what sensor types are available, how hot state fields work

The existing `POST /api/agents` endpoint handles basic creation (id, name, description, template, soul, model) but doesn't support the advanced config sections or guided iteration. Users need a conversational interface that understands the full schema and helps them build agents incrementally.

## Goals / Non-Goals

**Goals:**
- Users can create fully-configured agents (including autonomy, sensors, hot state) through conversation alone
- The builder agent is available immediately on every openhoof installation with zero setup
- The builder agent works with LlamaFarm by default but can use any configured inference provider
- Agent configurations are validated before being written, with clear error feedback
- Users can modify existing agents — update SOUL, add/remove tools, configure sensors, etc.

**Non-Goals:**
- Drag-and-drop visual agent builder with form-based config editing (the UI is chat-first)
- Multi-turn approval workflows for agent creation (the builder writes configs directly)
- Agent template marketplace or sharing
- Automatic agent testing or validation beyond config schema checks

## Decisions

### 1. Builder agent as a regular agent, not a special system component

**Decision**: The builder agent is a standard openhoof agent with its own workspace, SOUL.md, and agent.yaml — just like any user-created agent. It uses the same chat endpoint, same tool system, same inference pipeline.

**Why not a special system mode**: Keeping it as a regular agent means no new API surfaces, no special codepaths in the runtime, and the builder itself can be modified/improved by users. It also serves as a living example of a well-configured agent.

### 2. Bootstrap via package data with first-run provisioning

**Decision**: The builder agent's workspace files (SOUL.md, AGENTS.md, agent.yaml) are bundled as package data in `openhoof/agents/defaults/agent-builder/`. On startup, `AgentManager` checks if the `agent-builder` workspace exists in the agents directory. If not, it copies the defaults and auto-starts the agent.

**Why not generate from code**: Bundled files are editable, inspectable, and serve as documentation. Users can customize the builder's SOUL.md to change its personality or add domain-specific guidance. Code-generated configs would be opaque and harder to iterate on.

**Structure**:
```
openhoof/agents/defaults/agent-builder/
├── agent.yaml      # model: null (uses system default), tools: [configure_agent, list_agents, ...]
├── SOUL.md         # Builder identity, conversation flow guidance
└── AGENTS.md       # Workspace conventions
```

### 3. Single `configure_agent` tool with action parameter

**Decision**: One tool with an `action` parameter (create, read, update, delete) rather than four separate tools (create_agent, get_agent, update_agent, delete_agent).

**Why not separate tools**: The LLM needs to understand one tool schema instead of four. The actions share validation logic and context (agent_id, workspace path). A single tool with clear action semantics is easier for the model to reason about — it mirrors how a developer thinks: "I need to configure this agent" with different intents.

**Actions**:
- `create` — creates workspace dir, writes agent.yaml and SOUL.md, returns summary
- `read` — returns current agent.yaml + workspace file list
- `update` — merges partial config into existing agent.yaml, can update workspace files
- `delete` — stops agent if running, removes workspace directory

### 4. Partial-update semantics for agent modification

**Decision**: The `update` action accepts a partial config object. Only fields present in the update are changed; omitted fields are preserved. For nested objects (autonomy, hot_state), the merge is shallow — providing `autonomy: {enabled: true}` replaces the entire autonomy section, not just the `enabled` field.

**Why shallow merge for nested sections**: Deep merging complex nested configs (sensors list, hot_state fields map) creates ambiguity — does providing one sensor replace all sensors or add one? Shallow replacement per section is predictable. The builder agent can read the current config, modify it in conversation, and write back the full section.

### 5. Workspace file management via the same tool

**Decision**: The `configure_agent` tool's `update` action accepts an optional `files` parameter — a dict of `{filename: content}` for workspace files (SOUL.md, AGENTS.md, HEARTBEAT.md, etc.). This keeps all agent configuration in one tool rather than requiring the builder to use `memory_write` on another agent's workspace.

**Why not reuse memory_write**: `memory_write` operates on the calling agent's own workspace. The builder needs to write to other agents' workspaces. A dedicated parameter on `configure_agent` keeps the scope clear and avoids permission confusion.

### 6. Config validation before write

**Decision**: The `configure_agent` tool validates the config against the `AgentConfig` schema before writing. Invalid configs (e.g., sensor missing `interval`, unknown tool names, invalid hot_state field types) return a `ToolResult(success=False, error=...)` with specific validation errors so the builder can ask the user to correct the issue.

**Why validate in the tool**: Catching errors at config-write time is better than failing at agent-start time. The builder agent can surface validation errors conversationally and help the user fix them.

### 7. `list_agents` as a separate lightweight tool

**Decision**: A separate `list_agents` tool (not an action on `configure_agent`) that returns agent IDs, names, descriptions, status (running/stopped), and model. This is a read-only discovery tool useful beyond just the builder.

**Why separate**: Listing agents is a fundamentally different operation from configuring one. Keeping it separate means any agent can discover peers without needing the full configure_agent schema. It's also a natural first step in conversation: "What agents do I have?" → "Let me modify the fuel-analyst."

### 8. Builder SOUL designed for guided conversation

**Decision**: The builder agent's SOUL.md is carefully crafted with a conversation flow that guides users through agent creation step by step: (1) understand what the user wants to build, (2) suggest a name and description, (3) draft a SOUL, (4) recommend tools, (5) optionally configure advanced features (autonomy, sensors, hot state), (6) create the agent, (7) offer to start it.

**Why prescribe the flow in SOUL**: Without guidance, the LLM might try to create everything at once or ask too many questions upfront. A structured flow in the SOUL creates a good user experience — the builder knows when to ask questions, when to suggest defaults, and when to create.

### 9. Model-agnostic by default

**Decision**: The builder agent's `agent.yaml` sets `model: null`, which falls through to the system default model (LlamaFarm's default, typically qwen3-8b). Users can override this in the builder's own agent.yaml to use any model their inference adapter supports.

**Why null instead of hardcoded**: Setting `model: null` means the builder automatically uses whatever the system is configured for. If a user switches their openhoof instance to use Claude or OpenAI as the inference backend, the builder just works. No special model routing needed.

### 10. Dedicated builder UI page with enhanced chat experience

**Decision**: A new page at `/agents/builder` (or accessible via a prominent "Create Agent" button on the agents list page) that wraps the existing chat UI with builder-specific enhancements: a sidebar or header showing recently created/modified agents, inline status cards when the builder creates or modifies an agent (rendered from tool call results), and a quick-start prompt area for common actions ("Create a new agent", "Modify an existing agent", "List my agents").

**Why not just use the generic chat page**: The generic `/agents/[id]/chat` page works but gives no indication that this is a special-purpose agent. The builder UI should make the experience feel like a first-class feature — a clear entry point from the agents page, contextual feedback when agents are created/modified, and easy navigation to the newly created agent. The underlying chat mechanics are identical (same `/api/agents/agent-builder/chat` endpoint), but the UI layer adds builder-specific affordances.

**Why not a forms-based UI**: Forms for the full config schema (autonomy, sensors, hot state, etc.) would be enormous and rigid. The conversational approach handles the long tail of configuration better — the builder asks follow-up questions, suggests defaults, and explains trade-offs. The UI just needs to surface the conversation well and show the results.

**Key UI elements**:
- "Create Agent" button on `/agents` page that navigates to the builder chat
- Builder chat page with the same message bubbles as the generic chat
- Agent status cards rendered inline when the builder creates/updates an agent (parsed from tool results)
- Quick-action suggestions before the first message
- Link to navigate to a newly created agent's detail page

## Risks / Trade-offs

- **LLM accuracy on complex configs** — The builder agent may generate invalid sensor or hot_state configurations if the model doesn't fully understand the schema. → Mitigation: Config validation in the tool catches errors before write, and the SOUL includes schema documentation for the model's reference.

- **Builder agent modifiable by users** — Since it's a regular agent, users could break it by editing its SOUL.md or agent.yaml. → Mitigation: The bootstrap mechanism re-provisions defaults if the workspace is deleted. Could add a `reset` action or re-copy defaults on version upgrade.

- **Workspace file conflicts** — If an agent is running while the builder updates its config, the running agent won't pick up changes until restarted. → Mitigation: The `configure_agent` tool should stop and restart the agent after config changes, or at minimum warn the user.

- **No undo** — Delete is permanent, update overwrites. → Mitigation: The builder agent should confirm destructive actions in conversation before executing them. The SOUL prescribes confirmation for delete operations.

## Open Questions

- Should the builder agent be auto-started on system boot, or only started on first user interaction? (Leaning: auto-start via `autostart_agents` config default.)
- Should there be a `configure_agent` read action that returns the full config including workspace files, or just the YAML? (Leaning: YAML + file list, with a separate read for file contents.)
