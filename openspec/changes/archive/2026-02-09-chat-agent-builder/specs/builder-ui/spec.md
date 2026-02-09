## ADDED Requirements

### Requirement: Builder chat page
The UI SHALL provide a dedicated builder chat page at `/agents/builder` that presents a chat interface for conversing with the `agent-builder` agent. The page SHALL use the existing `/api/agents/agent-builder/chat` endpoint for message exchange. The chat SHALL display user and assistant messages in a familiar bubble layout consistent with the existing agent chat UI.

#### Scenario: User navigates to builder page
- **WHEN** a user navigates to `/agents/builder`
- **THEN** the page SHALL display a chat interface connected to the `agent-builder` agent with an empty conversation ready for input

#### Scenario: User sends message to builder
- **WHEN** a user types a message and submits it
- **THEN** the message SHALL be sent to the builder agent via the chat API and the response SHALL be displayed as an assistant message

#### Scenario: Chat history persists within session
- **WHEN** a user navigates away from the builder page and returns
- **THEN** the previous conversation messages SHALL still be displayed (within the same browser session)

### Requirement: Create Agent entry point
The agents list page (`/agents`) SHALL display a prominent "Create Agent" button that navigates to the builder chat page. The button SHALL be visually distinct and positioned near the top of the page alongside the existing agent list controls.

#### Scenario: Create Agent button on agents page
- **WHEN** a user views the agents list page
- **THEN** a "Create Agent" button SHALL be visible near the top of the page

#### Scenario: Create Agent button navigates to builder
- **WHEN** a user clicks the "Create Agent" button
- **THEN** the browser SHALL navigate to `/agents/builder`

### Requirement: Quick-action suggestions
The builder chat page SHALL display quick-action suggestion chips before the first message is sent. Suggestions SHALL include common starting prompts such as "Create a new agent", "Modify an existing agent", and "List my agents". Clicking a suggestion SHALL populate and send it as the user's first message.

#### Scenario: Suggestions shown on empty chat
- **WHEN** the builder chat page loads with no conversation history
- **THEN** quick-action suggestion chips SHALL be displayed in the chat area

#### Scenario: Suggestion clicked sends message
- **WHEN** a user clicks the "Create a new agent" suggestion chip
- **THEN** the text SHALL be sent as a chat message to the builder agent and the suggestions SHALL be hidden

#### Scenario: Suggestions hidden after first message
- **WHEN** the user sends their first message (typed or via suggestion)
- **THEN** the quick-action suggestions SHALL no longer be displayed

### Requirement: Agent status cards in chat
When the builder agent creates or modifies an agent (detected by `configure_agent` tool calls in the response), the UI SHALL render an inline agent status card within the chat flow. The card SHALL show the agent's name, ID, status, and a link to navigate to the agent's detail page.

#### Scenario: Agent created shows status card
- **WHEN** the builder agent's response includes a successful `configure_agent` create action
- **THEN** an agent status card SHALL be rendered inline in the chat showing the new agent's name, ID, and a "View Agent" link

#### Scenario: Agent updated shows status card
- **WHEN** the builder agent's response includes a successful `configure_agent` update action
- **THEN** an agent status card SHALL be rendered inline showing the updated agent's name and a "View Agent" link

#### Scenario: Status card links to agent detail
- **WHEN** a user clicks the "View Agent" link on a status card
- **THEN** the browser SHALL navigate to `/agents/{agent_id}` for the relevant agent

### Requirement: Builder page navigation
The builder chat page SHALL include navigation elements: a back link to the agents list, and the page title SHALL indicate this is the agent builder. The page SHALL be accessible from the main navigation sidebar in addition to the "Create Agent" button.

#### Scenario: Back navigation from builder
- **WHEN** a user is on the builder chat page
- **THEN** a back link or breadcrumb SHALL be visible that navigates to the agents list

#### Scenario: Builder accessible from sidebar
- **WHEN** a user views the main navigation sidebar
- **THEN** an entry for the agent builder SHALL be present (e.g., "Agent Builder" or within the Agents section)

### Requirement: Builder auto-start handling
If the builder agent is not running when the user navigates to the builder chat page, the UI SHALL automatically attempt to start it by calling `POST /api/agents/agent-builder/start`. If the builder agent does not exist (workspace missing), the UI SHALL display an error message suggesting the user restart the openhoof system to re-provision it.

#### Scenario: Builder not running on page load
- **WHEN** the user navigates to `/agents/builder` and the builder agent is stopped
- **THEN** the UI SHALL call the start endpoint and display the chat interface once the agent is running

#### Scenario: Builder workspace missing
- **WHEN** the user navigates to `/agents/builder` and the builder agent workspace does not exist
- **THEN** the UI SHALL display an error message: "The agent builder is not available. Please restart the openhoof system to re-provision it."

#### Scenario: Builder already running
- **WHEN** the user navigates to `/agents/builder` and the builder agent is already running
- **THEN** the chat interface SHALL be displayed immediately with no start delay
