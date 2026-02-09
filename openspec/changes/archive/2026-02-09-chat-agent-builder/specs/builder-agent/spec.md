## ADDED Requirements

### Requirement: Builder agent provisioning
The system SHALL include a default builder agent workspace bundled as package data at `openhoof/agents/defaults/agent-builder/`. The workspace SHALL contain `agent.yaml`, `SOUL.md`, and `AGENTS.md`. On startup, if no `agent-builder` workspace exists in the agents directory, the system SHALL copy the default workspace and register the agent for auto-start.

#### Scenario: First-run provisioning
- **WHEN** the `AgentManager` initializes and no `agent-builder` workspace exists in the agents directory
- **THEN** the system SHALL copy the default workspace from package data to the agents directory and add `agent-builder` to the auto-start list

#### Scenario: Existing builder workspace preserved
- **WHEN** the `AgentManager` initializes and an `agent-builder` workspace already exists
- **THEN** the system SHALL NOT overwrite the existing workspace and SHALL use the user's customized version

#### Scenario: Builder workspace deleted and re-provisioned
- **WHEN** a user deletes the `agent-builder` workspace directory and the system restarts
- **THEN** the system SHALL re-provision the default workspace from package data

### Requirement: Builder agent default configuration
The builder agent's `agent.yaml` SHALL configure: `model: null` (inherits system default), `tools` including `configure_agent`, `list_agents`, `memory_write`, and `memory_read`, `heartbeat_enabled: false`, and `max_tool_rounds: 10`. The agent SHALL NOT have autonomy, sensors, or hot state configured.

#### Scenario: Builder uses system default model
- **WHEN** the builder agent is started with `model: null` in its config
- **THEN** the system SHALL use the inference adapter's default model (e.g., LlamaFarm's default qwen3-8b)

#### Scenario: Builder model overridden
- **WHEN** a user edits the builder agent's `agent.yaml` to set `model: "claude-sonnet"` and the inference adapter supports that model
- **THEN** the builder agent SHALL use the specified model for all conversations

#### Scenario: Builder has required tools
- **WHEN** the builder agent is started
- **THEN** the agent SHALL have access to `configure_agent`, `list_agents`, `memory_write`, and `memory_read` tools

### Requirement: Builder agent SOUL
The builder agent's `SOUL.md` SHALL define its identity as an agent configuration assistant. The SOUL SHALL include: a mission statement focused on helping users create and modify agents, a prescribed conversation flow for agent creation (understand intent → suggest name/description → draft SOUL → recommend tools → configure advanced features → create agent → offer to start), schema documentation for all config sections (autonomy, hot_state, sensors), and guidance on when to suggest advanced features vs. keeping things simple.

#### Scenario: Builder guides new agent creation
- **WHEN** a user tells the builder "I want to create an agent that monitors stock prices"
- **THEN** the builder SHALL ask clarifying questions about the agent's purpose, suggest a name and description, and guide the user through configuration step by step

#### Scenario: Builder suggests appropriate complexity
- **WHEN** a user describes a simple agent (e.g., "a chatbot that answers questions about our docs")
- **THEN** the builder SHALL create a basic agent with just a SOUL, model, and relevant tools, without suggesting autonomy or sensors unless asked

#### Scenario: Builder suggests advanced features when appropriate
- **WHEN** a user describes an agent that needs to monitor data continuously (e.g., "watch for price alerts and trade automatically")
- **THEN** the builder SHALL suggest configuring autonomy, sensors, and hot state, explaining each feature's purpose

### Requirement: Builder agent auto-start
The builder agent SHALL be included in the system's default `autostart_agents` list so it is available immediately when the system starts. The auto-start SHALL happen after provisioning (if needed) and alongside any other configured auto-start agents.

#### Scenario: Builder auto-starts on system boot
- **WHEN** the openhoof system starts with default configuration
- **THEN** the builder agent SHALL be automatically started and available for chat

#### Scenario: Builder auto-start disabled by user
- **WHEN** a user removes `agent-builder` from the `autostart_agents` config
- **THEN** the builder agent SHALL NOT auto-start but SHALL remain available for manual start

### Requirement: Builder agent conversation via existing chat API
The builder agent SHALL be accessible via the existing `/api/agents/agent-builder/chat` endpoint. No new API endpoints SHALL be created for builder-specific functionality. All agent creation and modification SHALL happen through the builder's tool calls within normal chat turns.

#### Scenario: User chats with builder via API
- **WHEN** a client sends `POST /api/agents/agent-builder/chat` with a message
- **THEN** the builder agent SHALL respond using its SOUL-defined personality and tools

#### Scenario: Builder creates agent during chat
- **WHEN** the builder agent calls the `configure_agent` tool with action `create` during a chat turn
- **THEN** the agent SHALL be created on the filesystem and the builder SHALL report the result to the user in its response
