## ADDED Requirements

### Requirement: Theme toggle component
The UI SHALL provide a theme toggle button in the navigation bar that cycles through three modes: light, dark, and system. The button SHALL display an icon indicating the current mode (sun for light, moon for dark, monitor for system).

#### Scenario: Toggle from system to light
- **WHEN** the user clicks the theme toggle while in "system" mode
- **THEN** the mode SHALL change to "light", the `dark` class SHALL be removed from `<html>` regardless of OS preference, and the icon SHALL change to a sun

#### Scenario: Toggle from light to dark
- **WHEN** the user clicks the theme toggle while in "light" mode
- **THEN** the mode SHALL change to "dark", the `dark` class SHALL be added to `<html>`, and the icon SHALL change to a moon

#### Scenario: Toggle from dark to system
- **WHEN** the user clicks the theme toggle while in "dark" mode
- **THEN** the mode SHALL change to "system", the `dark` class SHALL be applied or removed based on the OS `prefers-color-scheme` setting, and the icon SHALL change to a monitor

### Requirement: Theme persistence
The UI SHALL persist the user's theme preference to `localStorage` under the key `openhoof-theme`. Values SHALL be `"light"`, `"dark"`, or `"system"`. When no value is stored, the default SHALL be `"system"`.

#### Scenario: Preference saved on toggle
- **WHEN** the user changes the theme mode
- **THEN** the new mode SHALL be written to `localStorage` under `openhoof-theme`

#### Scenario: Preference restored on page load
- **WHEN** the user loads the UI and `localStorage` contains `openhoof-theme: "dark"`
- **THEN** the UI SHALL apply dark mode immediately without user interaction

#### Scenario: Default to system on fresh visit
- **WHEN** the user loads the UI for the first time with no stored preference
- **THEN** the UI SHALL follow the OS `prefers-color-scheme` setting

### Requirement: Flash prevention
The UI SHALL prevent a flash of the wrong theme on page load. A synchronous inline script in the `<head>` SHALL read `localStorage` and apply the `dark` class to `<html>` before the browser's first paint.

#### Scenario: Dark mode user loads page
- **WHEN** a user with `openhoof-theme: "dark"` loads any page
- **THEN** the page SHALL render in dark mode from the first frame with no flash of light mode

#### Scenario: System mode user with dark OS preference
- **WHEN** a user with `openhoof-theme: "system"` and OS dark mode enabled loads any page
- **THEN** the page SHALL render in dark mode from the first frame

### Requirement: System preference tracking
When the theme mode is "system", the UI SHALL listen for changes to the OS `prefers-color-scheme` media query and update the theme in real time without requiring a page reload.

#### Scenario: OS switches to dark while UI is open
- **WHEN** the theme mode is "system" and the OS changes from light to dark mode
- **THEN** the UI SHALL immediately add the `dark` class to `<html>` and render in dark mode

#### Scenario: OS switches while mode is manual
- **WHEN** the theme mode is "light" (manual) and the OS changes to dark mode
- **THEN** the UI SHALL NOT change and SHALL remain in light mode

### Requirement: Dark-aware page styling
All UI pages SHALL render correctly in both light and dark themes. Hardcoded light-only color classes (e.g., `bg-white`, `bg-gray-50`, `text-gray-900`) SHALL be augmented with corresponding `dark:` variant classes. No page SHALL have unreadable text, invisible borders, or broken contrast in dark mode.

#### Scenario: Navigation bar in dark mode
- **WHEN** dark mode is active
- **THEN** the navigation bar SHALL have a dark background with light text and visible borders

#### Scenario: Agent list page in dark mode
- **WHEN** dark mode is active on the agents list page
- **THEN** the table, status badges, action buttons, and agent names SHALL be legible with appropriate dark background and light text colors

#### Scenario: Chat interface in dark mode
- **WHEN** dark mode is active on any chat page (agent chat or builder)
- **THEN** user message bubbles, assistant message bubbles, the input field, and loading indicators SHALL be clearly visible with appropriate contrast

#### Scenario: Dashboard in dark mode
- **WHEN** dark mode is active on the dashboard
- **THEN** agent cards, activity feed, stats, and status indicators SHALL render with appropriate dark backgrounds and light text

#### Scenario: Forms in dark mode
- **WHEN** dark mode is active on pages with form inputs (new agent, approvals)
- **THEN** input fields, textareas, labels, and buttons SHALL have appropriate dark-mode styling with visible borders and readable text

#### Scenario: Training dashboard in dark mode
- **WHEN** dark mode is active on the training page
- **THEN** charts, graphs, stat cards, and visualization elements SHALL render with appropriate dark-mode colors and contrast
