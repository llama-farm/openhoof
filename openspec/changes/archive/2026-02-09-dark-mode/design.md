## Context

The OpenHoof UI (Next.js 14 + Tailwind CSS) already has dark mode infrastructure partially in place:
- `globals.css` defines CSS variables for both `:root` (light) and `.dark` (dark) themes
- `tailwind.config.js` has `darkMode: ["class"]` and maps semantic color names (background, foreground, card, primary, etc.) to the CSS variables
- `globals.css` applies `bg-background text-foreground` to `body`

However, all 10+ page components use hardcoded Tailwind colors (`bg-white`, `bg-gray-50`, `text-gray-900`, etc.) — 162 occurrences across 11 files. Adding `.dark` to `<html>` currently has no visible effect because the page-level styles override the semantic body styles.

## Goals / Non-Goals

**Goals:**
- Users can toggle between light, dark, and system-follow modes
- Preference persists across sessions via localStorage
- All existing pages render correctly in both themes
- No flash of wrong theme on page load (FOHT prevention)

**Non-Goals:**
- Per-user theme stored server-side or in an API
- Custom theme colors beyond the existing light/dark palette
- Theme-aware syntax highlighting for code blocks (future)

## Decisions

### 1. Class-based toggle using existing Tailwind darkMode config

**Decision**: Toggle the `dark` class on `<html>` to activate Tailwind's class-based dark mode. This uses the existing `darkMode: ["class"]` config and `.dark` CSS variables already defined in `globals.css`.

**Why not media query approach**: The media query approach (`darkMode: "media"`) only follows system preference and doesn't allow manual override. Class-based gives users control while still supporting system preference as a default.

### 2. Inline script in layout for flash prevention

**Decision**: Add a blocking `<script>` in the `<head>` of `layout.tsx` that reads localStorage and applies the `dark` class before the first paint. This prevents the flash of light theme when a dark-mode user loads the page.

**Why not useEffect**: A React useEffect runs after hydration, causing a visible flash from light to dark. A synchronous `<script>` in `<head>` runs before the browser paints, eliminating the flash entirely.

### 3. Three-mode toggle: Light / Dark / System

**Decision**: The toggle offers three modes: "light" (always light), "dark" (always dark), "system" (follows OS `prefers-color-scheme`). "System" is the default for new users.

**Why include system mode**: Many users set OS-level dark mode schedules. Respecting this as the default means the UI "just works" for them without manual configuration. Power users can override to a fixed preference.

### 4. Replace hardcoded colors with Tailwind dark: variants

**Decision**: Migrate hardcoded color classes to use Tailwind's `dark:` variant prefix. For example:
- `bg-white` → `bg-white dark:bg-gray-900`
- `bg-gray-50` → `bg-gray-50 dark:bg-gray-950`
- `bg-gray-100` → `bg-gray-100 dark:bg-gray-800`
- `text-gray-900` → `text-gray-900 dark:text-gray-100`
- `text-gray-500` → `text-gray-500 dark:text-gray-400`
- `border-gray-200` → `border-gray-200 dark:border-gray-700`
- `shadow` → `shadow dark:shadow-gray-900/20`

**Why dark: variants over semantic tokens**: The existing pages use Tailwind utility classes extensively. Rewriting all pages to use `bg-card` / `text-foreground` everywhere would be a larger refactor with more risk of breakage. `dark:` variants are additive — they preserve the existing light styles and layer dark overrides. This is the standard Tailwind approach and keeps the migration incremental.

### 5. Toggle component in the navigation bar

**Decision**: A simple button in the top navigation bar (layout.tsx) that cycles through light → dark → system modes. The button shows an icon indicating the current mode (sun/moon/monitor). Clicking cycles to the next mode.

**Why not a dropdown**: A cycling button is simpler, takes less space in the nav bar, and three modes are easy to cycle through. A dropdown would be warranted with more options.

### 6. localStorage key convention

**Decision**: Store the theme preference in `localStorage` under the key `openhoof-theme`. Values: `"light"`, `"dark"`, `"system"`. If the key is absent, default to `"system"`.

## Risks / Trade-offs

- **Large diff across many files** — 162 color references in 11 files need updating. → Mitigation: Systematic find-and-replace with consistent mapping rules. Each page can be verified independently.

- **Training page complexity** — The training dashboard has 49 color references including SVG charts and custom visualizations. → Mitigation: Handle training page separately with extra attention to chart/SVG colors.

- **Third-party component compatibility** — Radix UI components may have their own color assumptions. → Mitigation: Radix primitives are unstyled; our Tailwind classes control their appearance.
