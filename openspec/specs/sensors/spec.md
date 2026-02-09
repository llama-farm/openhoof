## ADDED Requirements

### Requirement: Sensor framework
The system SHALL provide a sensor framework that runs background `asyncio.Task` instances to collect data from external sources and write results into the agent's hot state. Sensors SHALL be defined in the `sensors` section of `agent.yaml` and instantiated when the agent starts. Each sensor SHALL run independently and SHALL NOT crash the agent loop if it encounters errors.

#### Scenario: Sensors start with agent
- **WHEN** an agent with a `sensors` configuration starts
- **THEN** each configured sensor SHALL be instantiated and started as an async background task

#### Scenario: Sensors stop with agent
- **WHEN** an agent with running sensors is stopped
- **THEN** all sensor tasks SHALL be cancelled and cleaned up

#### Scenario: Sensor error does not crash agent
- **WHEN** a sensor encounters an error (network failure, invalid data, etc.)
- **THEN** the sensor SHALL log the error, apply exponential backoff before retrying, and continue running without affecting the agent loop or other sensors

### Requirement: Poll sensor type
The system SHALL support a `poll` sensor type that calls a data source at a fixed interval. The source SHALL be either a tool (by name, with optional params) or an HTTP URL. The sensor SHALL write the result to one or more hot state fields specified in its `updates` configuration.

#### Scenario: Poll sensor with tool source
- **WHEN** a poll sensor is configured with `source.tool: get_market_data` and `interval: 5`
- **THEN** the sensor SHALL call the `get_market_data` tool every 5 seconds and write the result to the configured hot state fields

#### Scenario: Poll sensor with URL source
- **WHEN** a poll sensor is configured with `source.url: "https://api.example.com/data"` and `interval: 10`
- **THEN** the sensor SHALL make an HTTP GET request to the URL every 10 seconds and write the response to the configured hot state fields

#### Scenario: Poll sensor with exponential backoff on error
- **WHEN** a poll sensor fails to fetch data
- **THEN** the sensor SHALL retry with exponential backoff (starting at the configured interval, doubling up to a max of 5 minutes) and resume the normal interval after a successful fetch

### Requirement: Watch sensor type
The system SHALL support a `watch` sensor type that monitors a file or directory for changes. When a change is detected, the sensor SHALL read the updated content and write it to the configured hot state fields.

#### Scenario: File change detected
- **WHEN** a watch sensor monitors `/var/data/signals.json` and the file is modified
- **THEN** the sensor SHALL read the updated file and write the contents to the configured hot state field

#### Scenario: Watched file does not exist initially
- **WHEN** a watch sensor is configured for a file that does not yet exist
- **THEN** the sensor SHALL wait for the file to appear without erroring, and process it when it is created

### Requirement: Stream sensor type
The system SHALL support a `stream` sensor type that connects to a streaming data source (WebSocket or SSE). The sensor SHALL process each incoming message and write results to the configured hot state fields.

#### Scenario: WebSocket stream connected
- **WHEN** a stream sensor is configured with a WebSocket URL
- **THEN** the sensor SHALL establish and maintain a WebSocket connection, processing each incoming message

#### Scenario: Stream reconnection on disconnect
- **WHEN** a stream sensor's connection drops
- **THEN** the sensor SHALL reconnect with exponential backoff and resume processing messages

### Requirement: Sensor data updates to hot state
Each sensor SHALL specify which hot state fields it updates via an `updates` configuration list. Each update entry SHALL name the target `field` in hot state. When the sensor receives data, it SHALL write the result to each configured field.

#### Scenario: Sensor updates multiple fields
- **WHEN** a sensor is configured with `updates: [{field: last_prices}, {field: indicators}]`
- **THEN** the sensor SHALL extract and write the appropriate data to both `last_prices` and `indicators` hot state fields on each data fetch

#### Scenario: Sensor updates field that does not exist in schema
- **WHEN** a sensor tries to update a hot state field not defined in the `hot_state` schema
- **THEN** the system SHALL log a warning and ignore the update

### Requirement: ML signal detection
A sensor SHALL support an optional `signals` configuration where each signal specifies a lightweight ML `model`, a `prompt`, a `threshold` (float, 0-1), and a `notify` flag (bool). On each data fetch, the sensor SHALL run the model with the prompt and data. If the model's score exceeds the threshold, the signal SHALL be considered fired.

#### Scenario: Signal fires and pushes notification
- **WHEN** a signal with `model: qwen3-1.7b`, `threshold: 0.8`, and `notify: true` evaluates data and the model returns a score of 0.9
- **THEN** the sensor SHALL push a notification to the hot state notification queue containing the signal name, score, and triggering data

#### Scenario: Signal below threshold
- **WHEN** a signal evaluates data and the model returns a score of 0.5 against a threshold of 0.8
- **THEN** no notification SHALL be pushed and no special action SHALL be taken

#### Scenario: Signal with cooldown
- **WHEN** a signal is configured with `cooldown: 300` (5 minutes) and fires
- **THEN** the signal SHALL NOT fire again within 300 seconds even if subsequent data exceeds the threshold

### Requirement: Sensor configuration
Each sensor in `agent.yaml` SHALL define: `name` (string, unique per agent), `type` ("poll", "watch", or "stream"), and type-specific fields. Poll sensors SHALL require `interval` (int, seconds) and `source` (tool or url). Watch sensors SHALL require `path` (string). Stream sensors SHALL require `source.url` (string). All sensor types SHALL support `updates` (list of field mappings) and `signals` (list of ML signal configs).

#### Scenario: Valid poll sensor config
- **WHEN** an agent config contains a poll sensor with name, type, interval, source, and updates
- **THEN** the system SHALL instantiate the sensor and start it when the agent starts

#### Scenario: Invalid sensor config
- **WHEN** a sensor config is missing required fields (e.g., poll sensor without interval)
- **THEN** the system SHALL log an error and skip that sensor without preventing the agent from starting

### Requirement: Sensor event emission
Each sensor SHALL emit events through the event bus for observability: `autonomy:sensor_updated` when it writes to hot state (with sensor name, field name, and timestamp). Sensor errors SHALL also be emitted as events for monitoring.

#### Scenario: Sensor update event
- **WHEN** a sensor successfully writes data to hot state
- **THEN** an `autonomy:sensor_updated` event SHALL be emitted with `agent_id`, `sensor_name`, `field`, and `timestamp`

#### Scenario: Sensor error event
- **WHEN** a sensor encounters an error
- **THEN** an `autonomy:sensor_error` event SHALL be emitted with `agent_id`, `sensor_name`, and `error` details
