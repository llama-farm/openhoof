## ADDED Requirements

### Requirement: Hot state store
The system SHALL provide a `HotState` object on each `AgentHandle` that holds structured, typed, in-memory state as a `Dict[str, HotStateField]`. Each field SHALL have a `value`, `updated_at` timestamp, `ttl` (seconds), and optional `refresh_tool` name. The hot state SHALL be ephemeral — not persisted to disk — and rebuilt from sensors and tools when the agent starts.

#### Scenario: Hot state created on agent start
- **WHEN** an agent with a `hot_state` configuration starts
- **THEN** a `HotState` object SHALL be created with fields initialized to `None` according to the schema, and stored on the `AgentHandle`

#### Scenario: Agent without hot state config
- **WHEN** an agent without a `hot_state` section starts
- **THEN** no `HotState` object SHALL be created, and the agent SHALL operate without hot state injection

### Requirement: Hot state schema in agent.yaml
The `agent.yaml` configuration SHALL support a `hot_state` section with a `fields` mapping. Each field SHALL define: `type` (string: "object", "number", "string", "array", "boolean"), `ttl` (int, seconds, optional), `refresh_tool` (string, optional tool name to call for refresh), and `max_items` (int, optional, for array types only).

#### Scenario: Schema with TTL and refresh tool
- **WHEN** a field is configured with `ttl: 30` and `refresh_tool: get_positions`
- **THEN** the system SHALL track staleness based on the TTL and support auto-refresh via the named tool

#### Scenario: Array field with max_items
- **WHEN** a field of type `array` is configured with `max_items: 20`
- **THEN** the system SHALL enforce the limit by dropping the oldest items when new items are appended beyond the limit

### Requirement: Hot state field updates
The system SHALL support updating hot state fields from three sources: (1) sensors writing data from background polling/streaming, (2) tool results that update state as a side effect, (3) the agent explicitly calling a `set_state` tool. Each update SHALL record the current timestamp as `updated_at`.

#### Scenario: Sensor updates a field
- **WHEN** a sensor receives new data and writes it to a hot state field
- **THEN** the field's `value` SHALL be updated and `updated_at` SHALL be set to the current time

#### Scenario: Tool result updates a field
- **WHEN** a tool with `refresh_tool` mapping is executed and returns a result
- **THEN** the corresponding hot state field SHALL be updated with the tool's result data

#### Scenario: Max items enforcement on array append
- **WHEN** an array field with `max_items: 20` receives a new item while already containing 20 items
- **THEN** the oldest item SHALL be removed before the new item is appended

### Requirement: Staleness tracking
Each hot state field SHALL track staleness based on its configured `ttl`. A field SHALL be considered stale when `now - updated_at > ttl`. Fields without a TTL SHALL never be considered stale. The system SHALL expose a method to get all stale fields and a method to check if a specific field is stale.

#### Scenario: Field within TTL
- **WHEN** a field with `ttl: 30` was updated 15 seconds ago
- **THEN** the field SHALL NOT be considered stale

#### Scenario: Field past TTL
- **WHEN** a field with `ttl: 30` was updated 45 seconds ago
- **THEN** the field SHALL be considered stale

#### Scenario: Field with no TTL
- **WHEN** a field has no `ttl` configured
- **THEN** the field SHALL never be considered stale regardless of when it was last updated

### Requirement: Auto-refresh of stale fields
Before each autonomous turn, the system SHALL check for stale fields that have a `refresh_tool` configured. For each such field, the system SHALL execute the named tool and update the field with the result. Auto-refresh SHALL happen after the pre-check gate passes but before the LLM context is built.

#### Scenario: Stale field with refresh tool
- **WHEN** a field with `refresh_tool: get_positions` is stale at the start of an autonomous turn
- **THEN** the system SHALL call the `get_positions` tool and update the field before building the LLM context

#### Scenario: Stale field without refresh tool
- **WHEN** a field without a `refresh_tool` is stale at the start of an autonomous turn
- **THEN** the system SHALL NOT attempt to refresh it and SHALL render it with a staleness marker in the context

#### Scenario: Refresh tool fails
- **WHEN** an auto-refresh tool call fails
- **THEN** the system SHALL keep the existing (stale) field value, log the error, and continue with the turn

### Requirement: Context injection
The system SHALL serialize the full hot state into a structured text block and inject it into the LLM system prompt before each autonomous turn. Each field SHALL be rendered with its name, current value, and a staleness marker if past its TTL (e.g., `(stale: 2m ago)`). Fields with `None` value SHALL be rendered as `(not yet loaded)`.

#### Scenario: Fresh hot state rendered
- **WHEN** all hot state fields have been recently updated within their TTLs
- **THEN** the injected block SHALL show each field with its value and no staleness markers

#### Scenario: Mixed staleness rendered
- **WHEN** some fields are fresh and some are stale
- **THEN** stale fields SHALL include a marker indicating how long ago they were updated (e.g., `(stale: 45s ago)`) and fresh fields SHALL have no marker

#### Scenario: Empty hot state
- **WHEN** an agent has hot state configured but no fields have been populated yet
- **THEN** each field SHALL be rendered as `(not yet loaded)` in the context block

### Requirement: Notification queue
The `HotState` SHALL maintain a notification queue — an ordered list of high-priority alerts pushed by sensors. Notifications SHALL be injected at the top of the agent's context on the next turn. After the agent observes them (the turn runs), the notifications SHALL be cleared from the queue.

#### Scenario: Notification pushed by sensor
- **WHEN** a sensor detects a high-priority condition and pushes a notification
- **THEN** the notification SHALL be appended to the queue and an `autonomy:notification_pushed` event SHALL be emitted

#### Scenario: Notifications injected into context
- **WHEN** an autonomous turn starts and the notification queue is non-empty
- **THEN** all pending notifications SHALL appear in a dedicated section at the top of the LLM context, before the hot state block

#### Scenario: Notifications cleared after turn
- **WHEN** an autonomous turn completes and notifications were present
- **THEN** the notification queue SHALL be cleared
