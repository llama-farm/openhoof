"use client";

import { useEffect, useState } from "react";

type ThemeMode = "light" | "dark" | "system";

const MODES: ThemeMode[] = ["system", "light", "dark"];

function applyTheme(mode: ThemeMode) {
  const dark =
    mode === "dark" ||
    (mode === "system" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

export default function ThemeToggle() {
  const [mode, setMode] = useState<ThemeMode>("system");

  // Initialize from localStorage
  useEffect(() => {
    const stored = localStorage.getItem("openhoof-theme") as ThemeMode | null;
    if (stored && MODES.includes(stored)) {
      setMode(stored);
    }
  }, []);

  // Listen for OS preference changes when in system mode
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    function onChange() {
      if (mode === "system") {
        applyTheme("system");
      }
    }
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [mode]);

  function cycle() {
    const nextIndex = (MODES.indexOf(mode) + 1) % MODES.length;
    const next = MODES[nextIndex];
    setMode(next);
    localStorage.setItem("openhoof-theme", next);
    applyTheme(next);
  }

  const icon = mode === "light" ? "\u2600\uFE0F" : mode === "dark" ? "\uD83C\uDF19" : "\uD83D\uDDA5\uFE0F";
  const label = mode === "light" ? "Light" : mode === "dark" ? "Dark" : "System";

  return (
    <button
      onClick={cycle}
      className="text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 text-sm flex items-center gap-1"
      title={`Theme: ${label}`}
    >
      <span>{icon}</span>
    </button>
  );
}
