## ADDED Requirements

### Requirement: Autonomous loop execution
The system SHALL run a continuous agent loop as an `asyncio.Task` on the `AgentHandle` when `autonomy.enabled` is `true` in the agent's configuration. The loop SHALL follow the sequence: observe (collect hot state + notifications) → think (LLM turn) → act (tool calls) → yield (agent-controlled pacing). The loop SHALL start when the agent starts and stop when the agent stops.

#### Scenario: Agent with autonomy enabled starts the loop
- **WHEN** an agent with `autonomy.enabled: true` is started via `AgentManager.start_agent()`
- **THEN** an `AutonomyLoop` asyncio task SHALL be created and stored on the `AgentHandle`, and the loop SHALL begin executing turns

#### Scenario: Agent without autonomy config behaves as before
- **WHEN** an agent without an `autonomy` section in its config is started
- **THEN** no autonomous loop SHALL be created, and the agent SHALL operate in reactive mode only (chat + heartbeat)

#### Scenario: Agent stop cancels the loop
- **WHEN** `AgentManager.stop_agent()` is called on an agent with a running autonomy loop
- **THEN** the loop task SHALL be cancelled, all sensors SHALL be stopped, and the agent SHALL shut down cleanly

### Requirement: Turn lifecycle
Each autonomous turn SHALL execute the following steps in order: (1) collect a hot state snapshot with staleness markers, (2) collect pending notifications, (3) run the pre-check gate, (4) auto-refresh stale hot state fields that have a `refresh_tool` configured, (5) build context from system prompt + hot state + notifications + recent transcript history, (6) execute an LLM turn via the existing `_run_agent_turn()` with a synthetic observe message, (7) parse the response for a yield tool call, (8) act on the yield directive.

#### Scenario: Normal turn with tool calls
- **WHEN** the pre-check gate passes and the LLM responds with tool calls followed by a yield
- **THEN** the system SHALL execute the tool calls via the existing tool registry, record the turn in the transcript, and act on the yield directive

#### Scenario: Pre-check gate skips a turn
- **WHEN** the pre-check gate determines nothing material has changed and no notifications are pending
- **THEN** the system SHALL skip the full LLM turn, emit an `autonomy:precheck_skipped` event, and extend the current sleep duration

#### Scenario: No yield tool called
- **WHEN** the LLM completes a turn without calling the yield tool
- **THEN** the system SHALL treat this as `yield(mode="continue")` and proceed immediately to the next turn

### Requirement: Pre-check gate
The system SHALL support an optional pre-check gate that runs a lightweight model before each full LLM turn. The gate SHALL receive a diff of hot state changes since the last turn and determine whether anything material has changed. If no pre-check model is configured, or if notifications are pending, the gate SHALL always pass (allowing the turn to proceed).

#### Scenario: Pre-check with configured model
- **WHEN** `autonomy.precheck_model` is configured and no notifications are pending
- **THEN** the system SHALL call the specified model with the hot state diff and only proceed to a full LLM turn if the model indicates material changes

#### Scenario: Pre-check bypassed when notifications pending
- **WHEN** the notification queue has pending alerts, regardless of pre-check model configuration
- **THEN** the pre-check gate SHALL pass and the full LLM turn SHALL proceed

### Requirement: Autonomy configuration
The `agent.yaml` configuration SHALL support an `autonomy` section with the following fields: `enabled` (bool), `max_consecutive_turns` (int), `token_budget_per_hour` (int), `max_actions_per_minute` (int), `idle_timeout` (int, seconds), `active_hours.start` (string, HH:MM), `active_hours.end` (string, HH:MM), and `precheck_model` (string, optional model name). All fields except `enabled` SHALL have sensible defaults.

#### Scenario: Minimal autonomy config
- **WHEN** an agent config contains `autonomy: {enabled: true}` with no other fields
- **THEN** the system SHALL use default values for all guardrail settings and start the autonomous loop

#### Scenario: Full autonomy config
- **WHEN** an agent config specifies all autonomy fields including active hours and precheck model
- **THEN** the system SHALL apply all specified values and only run during active hours

### Requirement: Guardrails
The autonomous loop SHALL enforce hard guardrails that the LLM cannot override. These SHALL include: `max_consecutive_turns` (force sleep after N turns without a sleep yield), `token_budget_per_hour` (pause agent when hourly token usage exceeds budget), `max_actions_per_minute` (rate limit on side-effect tool calls), and `idle_timeout` (stop agent after N seconds of no meaningful activity). When a guardrail triggers, the system SHALL emit an `autonomy:guardrail_triggered` event.

#### Scenario: Max consecutive turns reached
- **WHEN** the agent has executed `max_consecutive_turns` turns without calling `yield(mode="sleep")`
- **THEN** the system SHALL force a sleep of a default duration, emit a guardrail event, and log a warning

#### Scenario: Token budget exceeded
- **WHEN** the agent's cumulative token usage in the current hour exceeds `token_budget_per_hour`
- **THEN** the system SHALL pause the autonomous loop until the next hour boundary and emit a guardrail event

#### Scenario: Idle timeout
- **WHEN** the agent has not taken any meaningful action (tool calls with side effects) for `idle_timeout` seconds
- **THEN** the system SHALL stop the autonomous loop and emit a guardrail event

#### Scenario: Active hours enforcement
- **WHEN** the current time is outside the configured `active_hours` range
- **THEN** the autonomous loop SHALL sleep until the next active hours window begins

### Requirement: Event bus integration
The autonomous loop SHALL emit events through the existing event bus for all significant lifecycle moments: `autonomy:turn_started`, `autonomy:turn_completed`, `autonomy:precheck_skipped`, `autonomy:guardrail_triggered`. Each event SHALL include the `agent_id` and relevant context data.

#### Scenario: Turn events emitted
- **WHEN** an autonomous turn starts and completes
- **THEN** the system SHALL emit `autonomy:turn_started` (with turn number, hot state summary) and `autonomy:turn_completed` (with actions taken, yield decision) events

#### Scenario: Events visible via WebSocket
- **WHEN** a WebSocket client is subscribed to the autonomous agent
- **THEN** all autonomy events SHALL be broadcast to the client through the existing event bus WebSocket integration

### Requirement: Autonomous session isolation
The autonomous loop SHALL use a dedicated session key (`agent:{agent_id}:autonomy`) separate from the main chat session (`agent:{agent_id}:main`). This SHALL prevent autonomous turns from colliding with user chat interactions in the transcript.

#### Scenario: Concurrent chat and autonomy
- **WHEN** a user sends a chat message while the autonomous loop is running
- **THEN** the chat SHALL use the main session and the autonomous loop SHALL continue using its own session, with no transcript interference between them
