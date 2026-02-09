## Why

The OpenHoof UI is light-only despite having dark mode CSS variables and Tailwind `darkMode: ["class"]` already configured. Pages use hardcoded Tailwind colors (`bg-white`, `bg-gray-50`, `text-gray-900`) instead of semantic theme tokens, so adding `.dark` to the HTML element has no effect. Users working in low-light environments or who prefer dark interfaces need a functional dark mode.

## What Changes

- **Theme toggle** — a light/dark/system mode switcher in the navigation bar that persists the user's choice to localStorage
- **Semantic color migration** — replace hardcoded color classes across all pages with dark-mode-aware equivalents (e.g., `bg-white` → `bg-card`, `text-gray-900` → `text-foreground`)
- **Dark class application** — logic in the root layout to apply/remove the `dark` class on `<html>` based on the user's preference, with system preference detection via `prefers-color-scheme`

## Capabilities

### New Capabilities
- `dark-mode`: Theme toggle component, localStorage persistence, system preference detection, semantic color migration across all UI pages, and dark-mode-aware styling for all existing views (dashboard, agents, chat, tools, training, activity, approvals, builder).

### Modified Capabilities
_(none — this is purely a UI change with no backend or spec-level behavior changes)_

## Impact

- **UI**: All page files under `ui/app/` need color class updates. Root layout gets the toggle and dark class logic. `globals.css` dark variables are already defined and need no changes.
- **Code**: No backend changes. No API changes.
- **Dependencies**: No new dependencies — Tailwind dark mode and CSS variables are already configured.
