## 1. Configuration & Data Models

- [x] 1.1 Add `AutonomyConfig` dataclass with fields: `enabled`, `max_consecutive_turns`, `token_budget_per_hour`, `max_actions_per_minute`, `idle_timeout`, `active_hours` (start/end), `precheck_model` — all with sensible defaults
- [x] 1.2 Add `HotStateFieldConfig` dataclass with fields: `type`, `ttl`, `refresh_tool`, `max_items`
- [x] 1.3 Add `HotStateConfig` dataclass with a `fields: Dict[str, HotStateFieldConfig]` mapping
- [x] 1.4 Add `SensorConfig` dataclass with fields: `name`, `type` (poll/watch/stream), `interval`, `source` (tool/url/path), `updates` (list of field mappings), `signals` (list of ML signal configs)
- [x] 1.5 Extend `AgentConfig` with optional `autonomy: AutonomyConfig`, `hot_state: HotStateConfig`, and `sensors: List[SensorConfig]` fields
- [x] 1.6 Extend `AgentConfig.from_yaml()` to parse the new `autonomy`, `hot_state`, and `sensors` sections from `agent.yaml`
- [x] 1.7 Add new event type constants to `openhoof/core/events.py`: `autonomy:turn_started`, `autonomy:turn_completed`, `autonomy:precheck_skipped`, `autonomy:guardrail_triggered`, `autonomy:sensor_updated`, `autonomy:sensor_error`, `autonomy:notification_pushed`

## 2. Hot State

- [x] 2.1 Create `openhoof/core/hot_state.py` with `HotStateField` dataclass (value, updated_at, config) and `HotState` class with `fields` dict
- [x] 2.2 Implement `HotState.set(field_name, value)` — updates value and timestamp, enforces `max_items` on arrays
- [x] 2.3 Implement `HotState.get(field_name)` — returns current value
- [x] 2.4 Implement `HotState.is_stale(field_name)` and `HotState.get_stale_fields()` — staleness checking based on TTL
- [x] 2.5 Implement `HotState.render()` — serializes full hot state to a structured text block with staleness markers and `(not yet loaded)` for None values
- [x] 2.6 Implement `HotState.push_notification(name, data)` and `HotState.pop_notifications()` — notification queue management
- [x] 2.7 Implement `HotState.diff_since(timestamp)` — returns a summary of fields that changed since the given time (for pre-check gate)
- [x] 2.8 Write tests for HotState: set/get, staleness tracking, max_items enforcement, notification queue, render output, diff

## 3. Yield Tool

- [x] 3.1 Create `openhoof/tools/builtin/yield_tool.py` with `YieldTool` class extending `Tool` — parameters: `mode` (enum: sleep/continue/shutdown), `sleep` (int), `reason` (string), `wake_early_if` (list of strings)
- [x] 3.2 Implement `YieldTool.execute()` — validates params, returns `ToolResult` with confirmation message (actual yield behavior is enacted by the loop, not the tool)
- [x] 3.3 Register the yield tool in `register_builtin_tools()` but mark it with a flag so it can be excluded from non-autonomous turns
- [x] 3.4 Write tests for YieldTool: valid sleep/continue/shutdown, invalid mode handling, parameter validation

## 4. Sensor Framework

- [x] 4.1 Create `openhoof/core/sensors.py` with abstract `Sensor` base class — `name`, `config`, `hot_state` reference, `start()`, `stop()`, async `_loop()` method
- [x] 4.2 Implement `PollSensor` — async loop that calls a tool or HTTP URL at `interval` seconds, writes results to configured hot state fields
- [x] 4.3 Implement `WatchSensor` — monitors a file/directory for changes using asyncio file polling, writes updated content to hot state fields
- [x] 4.4 Implement `StreamSensor` — connects to WebSocket or SSE source, processes incoming messages and writes to hot state fields, with reconnection on disconnect
- [x] 4.5 Implement exponential backoff on sensor errors — start at configured interval, double up to 5 minute cap, reset on success
- [x] 4.6 Implement ML signal detection on sensors — optional `signals` config runs a lightweight model per data fetch, pushes notification to hot state queue if score exceeds threshold, respects cooldown
- [x] 4.7 Implement `sensor_factory(config, hot_state, tool_registry, inference)` — instantiates the correct sensor type from config, logs and skips invalid configs
- [x] 4.8 Add event emission to sensors — `autonomy:sensor_updated` on hot state write, `autonomy:sensor_error` on errors
- [x] 4.9 Write tests for PollSensor (tool source, URL source, backoff), WatchSensor (file change detection), and signal detection (threshold, cooldown, notification push)

## 5. Autonomy Loop

- [x] 5.1 Create `openhoof/agents/autonomy_loop.py` with `AutonomyLoop` class — holds references to agent handle, hot state, sensors, config, tool registry, inference adapter
- [x] 5.2 Implement `AutonomyLoop.start()` — creates the asyncio task for `_loop()`, starts all sensors
- [x] 5.3 Implement `AutonomyLoop.stop()` — cancels the loop task, stops all sensors, clean shutdown
- [x] 5.4 Implement the main `_loop()` method — continuous loop that calls `_run_turn()` and handles yield/sleep/shutdown between turns
- [x] 5.5 Implement `_run_turn()` — the full turn lifecycle: collect hot state snapshot, collect notifications, run pre-check gate, auto-refresh stale fields, build context message with hot state + notifications, call `_run_agent_turn()`, parse yield from response
- [x] 5.6 Implement pre-check gate — calls lightweight model with hot state diff, skips turn if no material changes (always passes if notifications pending or no precheck model configured)
- [x] 5.7 Implement auto-refresh — before building context, find stale fields with `refresh_tool`, call each tool, update hot state
- [x] 5.8 Implement context building — construct the synthetic observe message with rendered hot state block, notification section, and turn prompt
- [x] 5.9 Implement yield parsing — scan tool calls in the LLM response for the yield tool, extract mode/sleep/wake_early_if, default to `continue` if not found
- [x] 5.10 Implement sleep with wake-early-if — during sleep, poll the notification queue for matching events, cancel sleep early if match found
- [x] 5.11 Implement yield tool filtering — ensure the yield tool is included in tool schemas for autonomous turns only (not chat or heartbeat turns)
- [x] 5.12 Emit `autonomy:turn_started` and `autonomy:turn_completed` events with turn number, hot state summary, actions taken, yield decision
- [x] 5.13 Write tests for AutonomyLoop: turn lifecycle, pre-check gate skip, yield parsing (sleep/continue/shutdown), wake-early-if, default yield behavior

## 6. Guardrails

- [x] 6.1 Implement `max_consecutive_turns` tracking — counter increments on continue, resets on sleep, forces sleep when limit hit
- [x] 6.2 Implement `token_budget_per_hour` tracking — accumulate tokens per hour, pause loop until next hour when exceeded
- [x] 6.3 Implement `max_actions_per_minute` rate limiting — track side-effect tool calls, throttle if rate exceeded
- [x] 6.4 Implement `idle_timeout` — track last meaningful action timestamp, stop loop if idle too long
- [x] 6.5 Implement `active_hours` enforcement — check current time against configured window, sleep until next active period if outside
- [x] 6.6 Emit `autonomy:guardrail_triggered` event on each guardrail activation with guardrail type and details
- [x] 6.7 Write tests for each guardrail: consecutive turns cap, token budget, rate limiting, idle timeout, active hours

## 7. Lifecycle Integration

- [x] 7.1 Extend `AgentHandle` with optional fields: `autonomy_loop: AutonomyLoop`, `hot_state: HotState`, `sensors: List[Sensor]`
- [x] 7.2 Update `AgentManager.start_agent()` — if `autonomy.enabled`, create HotState from config, instantiate sensors, create and start AutonomyLoop
- [x] 7.3 Update `AgentManager.stop_agent()` — if autonomy loop is running, stop it (which stops sensors), then proceed with existing shutdown
- [x] 7.4 Use dedicated session key `agent:{agent_id}:autonomy` for autonomous turns to isolate from the main chat session
- [x] 7.5 Ensure existing chat flow is unaffected — agents without autonomy config behave exactly as before
- [x] 7.6 Write integration test: start agent with autonomy config, verify loop runs, send chat concurrently, stop agent, verify clean shutdown
