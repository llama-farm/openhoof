## ADDED Requirements

### Requirement: Yield tool
The system SHALL provide a `yield` tool registered in the tool registry that autonomous agents call to control their execution pacing. The tool SHALL accept the following parameters: `mode` (required, enum: "sleep", "continue", "shutdown"), `sleep` (int, seconds, required when mode is "sleep"), `reason` (string, optional, human-readable explanation), and `wake_early_if` (list of strings, optional, event names that should wake the agent early).

#### Scenario: Agent yields with sleep
- **WHEN** the agent calls `yield(mode="sleep", sleep=30, reason="monitoring, nothing actionable")`
- **THEN** the autonomous loop SHALL pause for 30 seconds before starting the next turn

#### Scenario: Agent yields with continue
- **WHEN** the agent calls `yield(mode="continue", reason="investigating anomaly")`
- **THEN** the autonomous loop SHALL proceed immediately to the next turn with no pause

#### Scenario: Agent yields with shutdown
- **WHEN** the agent calls `yield(mode="shutdown", reason="market closed")`
- **THEN** the autonomous loop SHALL stop, sensors SHALL be stopped, and an `autonomy:turn_completed` event SHALL be emitted with the shutdown reason

### Requirement: Wake-early-if conditions
When the agent specifies `wake_early_if` event names in a sleep yield, the runtime SHALL monitor the notification queue during the sleep period. If a notification matching any of the specified event names arrives before the sleep expires, the runtime SHALL cancel the remaining sleep and start the next turn immediately.

#### Scenario: Wake early on matching notification
- **WHEN** the agent calls `yield(mode="sleep", sleep=300, wake_early_if=["order_filled"])` and an `order_filled` notification arrives after 20 seconds
- **THEN** the runtime SHALL cancel the remaining 280 seconds of sleep and start the next turn immediately

#### Scenario: No matching notification during sleep
- **WHEN** the agent calls `yield(mode="sleep", sleep=60, wake_early_if=["stop_loss_triggered"])` and no matching notification arrives
- **THEN** the runtime SHALL sleep for the full 60 seconds before starting the next turn

#### Scenario: Wake early with non-matching notification
- **WHEN** the agent calls `yield(mode="sleep", sleep=60, wake_early_if=["order_filled"])` and a `price_alert` notification arrives
- **THEN** the runtime SHALL NOT wake early and SHALL continue sleeping for the full duration (the notification will be seen on the next turn)

### Requirement: Yield tool only available in autonomous mode
The `yield` tool SHALL only be included in the tool schemas passed to the LLM during autonomous loop turns. It SHALL NOT be available during regular chat turns or heartbeat turns, as it has no meaning outside the autonomous loop context.

#### Scenario: Yield tool in autonomous turn
- **WHEN** the tool schemas are built for an autonomous loop turn
- **THEN** the `yield` tool SHALL be included in the available tools

#### Scenario: Yield tool absent in chat turn
- **WHEN** the tool schemas are built for a regular chat turn
- **THEN** the `yield` tool SHALL NOT be included in the available tools

### Requirement: Yield tool result
The `yield` tool SHALL always return a successful `ToolResult` with a message confirming the yield action (e.g., "Sleeping for 30s", "Continuing immediately", "Shutting down"). The actual yield behavior is enacted by the loop runner after the turn completes, not by the tool itself.

#### Scenario: Yield tool returns confirmation
- **WHEN** the agent calls the yield tool with any valid parameters
- **THEN** the tool SHALL return `ToolResult(success=True, message="...")` describing the yield action

#### Scenario: Yield tool with invalid mode
- **WHEN** the agent calls the yield tool with an invalid mode value
- **THEN** the tool SHALL return `ToolResult(success=False, error="Invalid mode: ...")` and the loop SHALL treat it as `yield(mode="continue")`

### Requirement: Default yield behavior
When the agent completes an autonomous turn without calling the yield tool, the runtime SHALL treat this as an implicit `yield(mode="continue")`. This ensures the loop always advances and the `max_consecutive_turns` guardrail can count turns that never sleep.

#### Scenario: No yield call in response
- **WHEN** the LLM responds with text and/or tool calls but does not call the yield tool
- **THEN** the loop SHALL proceed immediately to the next turn as if `yield(mode="continue")` was called

#### Scenario: Consecutive turn counter increments
- **WHEN** the agent completes a turn with an implicit or explicit `yield(mode="continue")`
- **THEN** the consecutive turn counter SHALL increment, and the counter SHALL reset to zero only when a `yield(mode="sleep")` is executed
