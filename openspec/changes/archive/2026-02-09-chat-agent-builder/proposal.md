## Why

Creating agents today requires hand-editing YAML configs and workspace files — a process that demands knowledge of the config schema, available tools, sensor types, hot state fields, and autonomy settings. Users should be able to define and modify agents through natural conversation with a builder agent that ships with every openhoof installation.

## What Changes

- A new **builder agent** (`agent-builder`) pre-installed in every openhoof system, with a SOUL focused on guiding users through agent creation and modification via conversation
- A new **`configure_agent` tool** that programmatically creates, reads, updates, and deletes agent configurations (YAML + workspace files) so the builder agent can act on the user's intent
- A new **`list_agents` tool** that lets any agent discover what agents exist on the system, their status, and capabilities
- A **bootstrap mechanism** that ensures the builder agent's workspace is created on first startup if it doesn't already exist
- The builder agent uses **LlamaFarm as its default LLM** but supports switching to any configured model (Claude, OpenAI, Gemini, etc. via inference adapter config)
- A **dedicated UI view** in the openhoof web interface for chatting with the builder agent — a prominent entry point (e.g., "Create Agent" button on the agents page) that opens a purpose-built chat experience with builder-specific affordances like agent creation status and quick actions

## Capabilities

### New Capabilities
- `builder-agent`: The pre-installed conversational agent, its SOUL, bootstrap lifecycle, and default configuration. Covers how it's provisioned, how it guides users through agent creation/modification, and how it handles model selection.
- `agent-config-tools`: The `configure_agent` and `list_agents` tools — parameter schemas, CRUD operations, validation, workspace file management, and safe defaults for complex config sections (autonomy, sensors, hot state).
- `builder-ui`: The web UI view for interacting with the builder agent — entry points from the agents page, the chat experience with builder-specific enhancements (agent status cards, creation progress), and navigation flow.

### Modified Capabilities
_(none — existing specs are unaffected; the builder agent uses existing lifecycle, tools, and inference infrastructure as-is)_

## Impact

- **Code**: New tool classes in `openhoof/tools/builtin/`, new bootstrap logic in agent lifecycle startup, builder agent workspace files in a well-known location
- **Config**: The builder agent's `agent.yaml` and SOUL.md ship as package data or are generated on first run
- **UI**: New Next.js page for the builder chat experience, updated agents page with "Create Agent" entry point
- **APIs**: No new API endpoints — the builder agent is used via the existing `/api/agents/{agent_id}/chat` endpoint
- **Dependencies**: No new dependencies — uses existing inference adapters, tool registry, workspace system
