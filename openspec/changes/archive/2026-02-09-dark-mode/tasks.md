## 1. Theme Infrastructure

- [x] 1.1 Add inline theme script to `layout.tsx` `<head>` that reads `localStorage("openhoof-theme")` and applies `dark` class to `<html>` before first paint
- [x] 1.2 Create `ThemeToggle` component (`ui/app/components/ThemeToggle.tsx`) — cycling button (light→dark→system) with sun/moon/monitor icons, writes to localStorage, toggles `dark` class on `<html>`
- [x] 1.3 Add `ThemeToggle` to the navigation bar in `layout.tsx`
- [x] 1.4 Add `prefers-color-scheme` media query listener in `ThemeToggle` that updates `dark` class in real time when mode is "system"

## 2. Navigation & Layout Dark Styling

- [x] 2.1 Migrate hardcoded colors in `layout.tsx` — nav bar bg, text colors, hover states, borders, page background (~16 refs)

## 3. Dashboard Dark Styling

- [x] 3.1 Migrate hardcoded colors in `page.tsx` (dashboard) — cards, shadows, text, stats, activity section (~21 refs)

## 4. Agents Pages Dark Styling

- [x] 4.1 Migrate hardcoded colors in `agents/page.tsx` — table, headers, dividers, buttons, hover states (~17 refs)
- [x] 4.2 Migrate hardcoded colors in `agents/new/page.tsx` — form container, labels, inputs, buttons (~8 refs)
- [x] 4.3 Migrate hardcoded colors in `agents/[id]/page.tsx` — detail panels, file list, tools section (~17 refs)
- [x] 4.4 Migrate hardcoded colors in `agents/[id]/chat/page.tsx` — message bubbles, input, loading indicator (~7 refs)
- [x] 4.5 Migrate hardcoded colors in `agents/builder/page.tsx` — chat container, suggestion chips, status cards (~10 refs)

## 5. Other Pages Dark Styling

- [x] 5.1 Migrate hardcoded colors in `tools/page.tsx` — tool cards, parameter badges, expanded sections (~12 refs)
- [x] 5.2 Migrate hardcoded colors in `activity/page.tsx` — feed items, JSON preview, hover states (~9 refs)
- [x] 5.3 Migrate hardcoded colors in `approvals/page.tsx` — approval cards, JSON preview, toggle links (~6 refs)

## 6. Training Dashboard Dark Styling

- [x] 6.1 Migrate hardcoded colors in `training/page.tsx` — stat cards, containers, text, badges, progress bars, SVG chart colors (~42 refs)

## 7. Verification

- [ ] 7.1 Visually verify all pages in dark mode — toggle through light/dark/system on every page, check for unreadable text, invisible borders, or broken contrast
- [x] 7.2 Verify flash prevention — inline script in `<head>` reads localStorage and applies `dark` class before first paint
- [x] 7.3 Verify localStorage persistence — ThemeToggle writes mode to `openhoof-theme` key on every toggle, inline script reads it on load
- [x] 7.4 Verify system preference tracking — ThemeToggle registers `matchMedia` change listener when mode is "system"
