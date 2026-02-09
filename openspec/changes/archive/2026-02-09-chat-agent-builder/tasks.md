## 1. Agent Config Tools

- [x] 1.1 Implement `ConfigureAgentTool` class in `openhoof/tools/builtin/configure_agent.py` with `action` parameter (create/read/update/delete), `agent_id`, `config`, and `files` parameters, and full OpenAI-compatible parameter schema
- [x] 1.2 Implement `create` action: create workspace directory, write `agent.yaml` from config dict, write workspace files from `files` param, generate default SOUL.md if not provided, return agent summary
- [x] 1.3 Implement `read` action: load and return `agent.yaml` contents and workspace file listing with sizes
- [x] 1.4 Implement `update` action: load existing `agent.yaml`, apply shallow merge (top-level scalars replaced individually, nested objects like autonomy/hot_state/sensors replaced as whole sections), write workspace files from `files` param, warn if agent is running
- [x] 1.5 Implement `delete` action: stop agent if running (via AgentManager), remove workspace directory, prevent deletion of `agent-builder`
- [x] 1.6 Implement config validation: check required fields, field types, enum values (sensor types, hot_state field types), structural constraints (poll sensors require interval, watch sensors require path), agent_id format (kebab-case). Return specific error messages on failure.
- [x] 1.7 Implement safe defaults: fill in autonomy defaults (max_consecutive_turns: 50, etc.), hot_state field defaults (type: object), sensor signal defaults (threshold: 0.8, notify: true)
- [x] 1.8 Implement `ListAgentsTool` class in `openhoof/tools/builtin/list_agents.py` with optional `status` filter (all/running/stopped), returning agent_id, name, description, status, model, and autonomy_enabled for each agent
- [x] 1.9 Register both tools in `openhoof/tools/builtin/__init__.py`
- [x] 1.10 Write tests for `configure_agent` tool: create with full config, create with minimal config, create with duplicate ID, read existing, read non-existent, update scalars, update nested section replacement, update files, update non-existent, update running agent warning, delete stopped, delete running, delete non-existent, delete builder prevented, validation errors (invalid sensor, invalid hot_state type, invalid agent_id format), safe defaults
- [x] 1.11 Write tests for `list_agents` tool: list all, list running only, list stopped only, empty system, agent details include expected fields

## 2. Builder Agent Workspace Defaults

- [x] 2.1 Create `openhoof/agents/defaults/agent-builder/agent.yaml` with model: null, tools: [configure_agent, list_agents, memory_write, memory_read], heartbeat_enabled: false, max_tool_rounds: 10
- [x] 2.2 Create `openhoof/agents/defaults/agent-builder/SOUL.md` with builder identity, mission statement, prescribed conversation flow (understand intent → suggest name/description → draft SOUL → recommend tools → configure advanced features → create → offer to start), schema reference for autonomy/hot_state/sensors config sections, guidance on complexity (simple vs. advanced agents)
- [x] 2.3 Create `openhoof/agents/defaults/agent-builder/AGENTS.md` with workspace conventions for the builder agent

## 3. Builder Agent Bootstrap and Auto-start

- [x] 3.1 Add provisioning logic to `AgentManager` initialization: check if `agent-builder` workspace exists in agents directory, if not copy from `openhoof/agents/defaults/agent-builder/` package data
- [x] 3.2 Add `agent-builder` to the default `autostart_agents` list in system config so it starts on boot
- [x] 3.3 Ensure provisioning runs before auto-start (agent must exist before it can be started)
- [x] 3.4 Include `openhoof/agents/defaults/` in package data via `pyproject.toml` so files are bundled with the package
- [x] 3.5 Write tests for provisioning: first-run copies defaults, existing workspace preserved, re-provision after deletion

## 4. Builder UI — Chat Page

- [x] 4.1 Create `/agents/builder` page in `ui/app/agents/builder/page.tsx` with chat interface (message bubbles, input field, send button) connected to `/api/agents/agent-builder/chat`
- [x] 4.2 Implement auto-start logic: on page load check agent status, if stopped call start endpoint, if workspace missing show error message, if running show chat immediately
- [x] 4.3 Implement quick-action suggestion chips: "Create a new agent", "Modify an existing agent", "List my agents" — shown on empty chat, hidden after first message, clicking sends as message
- [x] 4.4 Implement agent status cards: parse assistant messages for configure_agent tool results, render inline cards with agent name, ID, status, and "View Agent" link to `/agents/{agent_id}`
- [x] 4.5 Add page header with title ("Agent Builder") and back link/breadcrumb to agents list

## 5. Builder UI — Navigation and Entry Points

- [x] 5.1 Add "Create Agent" button to agents list page (`ui/app/agents/page.tsx`) positioned prominently near the top, navigating to `/agents/builder`
- [x] 5.2 Add "Agent Builder" entry to the main navigation sidebar in `ui/app/layout.tsx`
- [x] 5.3 Ensure chat history persists within browser session (messages stored in React state, preserved on navigation within session)

## 6. Integration Testing

- [x] 6.1 Write integration test: full agent creation flow — builder agent receives "create a stock watcher" message, calls configure_agent create, workspace exists on disk with valid agent.yaml and SOUL.md
- [x] 6.2 Write integration test: agent modification flow — builder reads existing agent, updates config, verify shallow merge applied correctly
- [x] 6.3 Write integration test: provisioning + auto-start — system starts, builder workspace provisioned, builder agent running and responding to chat
