## ADDED Requirements

### Requirement: configure_agent tool
The system SHALL provide a `configure_agent` tool registered in the tool registry that performs CRUD operations on agent configurations. The tool SHALL accept the following parameters: `action` (required, enum: "create", "read", "update", "delete"), `agent_id` (required, string), `config` (object, required for create, optional for update), and `files` (object, optional, map of filename to content for workspace files).

#### Scenario: Tool registered at startup
- **WHEN** the tool registry initializes
- **THEN** the `configure_agent` tool SHALL be registered and available to any agent that includes it in its tools list

#### Scenario: Tool schema is valid OpenAI format
- **WHEN** the tool registry generates OpenAI schemas
- **THEN** the `configure_agent` tool SHALL produce a valid OpenAI function schema with all parameters documented

### Requirement: configure_agent create action
The `create` action SHALL create a new agent workspace directory, write `agent.yaml` from the provided config, and write any workspace files specified in the `files` parameter. At minimum, the `config` SHALL include `name`. If no `SOUL.md` is provided in `files`, the tool SHALL generate a default SOUL from the agent's name and description. The tool SHALL return a `ToolResult` with the created agent's ID, name, and workspace path.

#### Scenario: Create agent with config and SOUL
- **WHEN** the tool is called with `action: "create"`, `agent_id: "stock-watcher"`, `config: {name: "Stock Watcher", description: "Monitors stock prices", model: "qwen3-8b", tools: ["notify"]}`, and `files: {"SOUL.md": "You are a stock price monitor..."}`
- **THEN** the tool SHALL create the workspace directory, write `agent.yaml` with the specified config, write `SOUL.md` with the provided content, and return success with the agent details

#### Scenario: Create agent with minimal config
- **WHEN** the tool is called with `action: "create"`, `agent_id: "helper"`, `config: {name: "Helper"}`, and no `files`
- **THEN** the tool SHALL create the workspace, write `agent.yaml`, generate a default `SOUL.md` based on the name, and return success

#### Scenario: Create agent with duplicate ID
- **WHEN** the tool is called with `action: "create"` and `agent_id` matches an existing agent workspace
- **THEN** the tool SHALL return `ToolResult(success=False, error="Agent 'stock-watcher' already exists")` without modifying the existing agent

#### Scenario: Create agent with advanced config
- **WHEN** the tool is called with `action: "create"` and `config` includes `autonomy`, `hot_state`, and `sensors` sections
- **THEN** the tool SHALL validate all sections against the `AgentConfig` schema and write the complete configuration

### Requirement: configure_agent read action
The `read` action SHALL return the current agent configuration and workspace file listing. The result SHALL include the parsed `agent.yaml` contents and a list of all files in the workspace directory with their sizes.

#### Scenario: Read existing agent
- **WHEN** the tool is called with `action: "read"` and `agent_id: "fuel-analyst"`
- **THEN** the tool SHALL return the agent's config (parsed from `agent.yaml`) and a list of workspace files

#### Scenario: Read non-existent agent
- **WHEN** the tool is called with `action: "read"` and `agent_id` does not match any workspace
- **THEN** the tool SHALL return `ToolResult(success=False, error="Agent 'unknown-agent' not found")`

### Requirement: configure_agent update action
The `update` action SHALL merge the provided `config` into the existing `agent.yaml` using shallow merge semantics: top-level scalar fields are replaced individually, but nested objects (`autonomy`, `hot_state`, `sensors`) are replaced as whole sections when present. The `files` parameter SHALL overwrite or create the specified workspace files. The tool SHALL return the updated config summary.

#### Scenario: Update scalar fields
- **WHEN** the tool is called with `action: "update"`, `agent_id: "stock-watcher"`, and `config: {description: "Updated description", model: "qwen3-1.7b"}`
- **THEN** the tool SHALL update only `description` and `model` in `agent.yaml`, preserving all other fields

#### Scenario: Update nested section replaces entirely
- **WHEN** the tool is called with `action: "update"` and `config: {autonomy: {enabled: true, max_consecutive_turns: 20}}`
- **THEN** the tool SHALL replace the entire `autonomy` section with the provided object, not merge individual fields into an existing section

#### Scenario: Update workspace files
- **WHEN** the tool is called with `action: "update"` and `files: {"SOUL.md": "Updated soul content", "HEARTBEAT.md": "Check status every hour"}`
- **THEN** the tool SHALL overwrite `SOUL.md` and create `HEARTBEAT.md` in the agent's workspace

#### Scenario: Update non-existent agent
- **WHEN** the tool is called with `action: "update"` and `agent_id` does not exist
- **THEN** the tool SHALL return `ToolResult(success=False, error="Agent 'unknown-agent' not found")`

#### Scenario: Update running agent
- **WHEN** the tool is called with `action: "update"` on an agent that is currently running
- **THEN** the tool SHALL update the config files and include a note in the result message that the agent must be restarted for changes to take effect

### Requirement: configure_agent delete action
The `delete` action SHALL stop the agent if running, then remove the entire workspace directory. The tool SHALL return confirmation of the deletion.

#### Scenario: Delete stopped agent
- **WHEN** the tool is called with `action: "delete"` and `agent_id: "old-agent"` and the agent is not running
- **THEN** the tool SHALL remove the workspace directory and return success

#### Scenario: Delete running agent
- **WHEN** the tool is called with `action: "delete"` and the agent is currently running
- **THEN** the tool SHALL stop the agent first, then remove the workspace directory, and return success

#### Scenario: Delete non-existent agent
- **WHEN** the tool is called with `action: "delete"` and `agent_id` does not exist
- **THEN** the tool SHALL return `ToolResult(success=False, error="Agent 'unknown-agent' not found")`

#### Scenario: Delete builder agent prevented
- **WHEN** the tool is called with `action: "delete"` and `agent_id: "agent-builder"`
- **THEN** the tool SHALL return `ToolResult(success=False, error="Cannot delete the builder agent")` to prevent the builder from deleting itself

### Requirement: configure_agent config validation
The `configure_agent` tool SHALL validate all config data against the `AgentConfig` schema before writing to disk. Validation SHALL check: required fields, field types, enum values (sensor types, hot_state field types), and structural constraints (poll sensors require interval, watch sensors require path). Invalid configs SHALL return `ToolResult(success=False, error=...)` with specific validation error messages.

#### Scenario: Valid config passes validation
- **WHEN** the tool receives a config with all required fields and valid values
- **THEN** the tool SHALL write the config to disk and return success

#### Scenario: Invalid sensor config rejected
- **WHEN** the tool receives a config with a poll sensor missing the `interval` field
- **THEN** the tool SHALL return `ToolResult(success=False, error="Sensor 'my-sensor': poll type requires 'interval' field")` without writing

#### Scenario: Invalid hot_state field type rejected
- **WHEN** the tool receives a config with a hot_state field type of "invalid_type"
- **THEN** the tool SHALL return `ToolResult(success=False, error="Hot state field 'my_field': type must be one of: object, number, string, array, boolean")` without writing

#### Scenario: Invalid agent_id format rejected
- **WHEN** the tool receives an `agent_id` containing spaces or special characters
- **THEN** the tool SHALL return `ToolResult(success=False, error="Agent ID must be kebab-case (lowercase letters, numbers, hyphens)")` without writing

### Requirement: list_agents tool
The system SHALL provide a `list_agents` tool registered in the tool registry that returns information about all agents on the system. The tool SHALL accept an optional `status` parameter (enum: "all", "running", "stopped", default: "all"). The result SHALL include each agent's `agent_id`, `name`, `description`, `status` (running/stopped), and `model`.

#### Scenario: List all agents
- **WHEN** the tool is called with no parameters or `status: "all"`
- **THEN** the tool SHALL return a list of all agent workspaces with their metadata and running status

#### Scenario: List running agents only
- **WHEN** the tool is called with `status: "running"`
- **THEN** the tool SHALL return only agents that are currently running

#### Scenario: List agents on empty system
- **WHEN** the tool is called and only the builder agent exists
- **THEN** the tool SHALL return a list containing only the builder agent

#### Scenario: Agent details include config summary
- **WHEN** the tool returns agent information
- **THEN** each agent entry SHALL include `agent_id`, `name`, `description`, `status`, `model`, and whether autonomy is enabled

### Requirement: Safe defaults for complex config sections
When the `configure_agent` tool creates or updates an agent with complex config sections, it SHALL apply safe defaults for omitted fields. Autonomy defaults: `max_consecutive_turns: 50`, `token_budget_per_hour: 100000`, `max_actions_per_minute: 10`, `idle_timeout: 600`. Hot state field defaults: `type: "object"`, no TTL, no refresh tool. Sensor signal defaults: `threshold: 0.8`, `notify: true`, no cooldown.

#### Scenario: Autonomy with minimal config
- **WHEN** the tool receives `config: {autonomy: {enabled: true}}` with no other autonomy fields
- **THEN** the tool SHALL write the autonomy section with all default values filled in

#### Scenario: Hot state field with minimal config
- **WHEN** the tool receives a hot_state field with only `type: "number"`
- **THEN** the tool SHALL write the field config with no TTL and no refresh tool (field never goes stale)

#### Scenario: Sensor with required fields only
- **WHEN** the tool receives a poll sensor with only `name`, `type`, `interval`, and `source`
- **THEN** the tool SHALL write the sensor config with empty `updates` and `signals` lists
