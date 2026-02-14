"use client"

import { useTheme } from "next-themes"
import { useEffect, useState } from "react"
import { Sun, Moon, Monitor } from "lucide-react"

/** Compact icon-only toggle for the header bar */
export function ThemeToggle() {
  const { theme, setTheme, resolvedTheme } = useTheme()
  const [mounted, setMounted] = useState(false)

  useEffect(() => setMounted(true), [])
  if (!mounted) {
    return (
      <div className="h-8 w-8 rounded-lg bg-secondary animate-pulse" />
    )
  }

  const cycle = () => {
    document.documentElement.classList.add("transitioning")
    setTimeout(() => document.documentElement.classList.remove("transitioning"), 350)

    if (theme === "system") setTheme("light")
    else if (theme === "light") setTheme("dark")
    else setTheme("system")
  }

  const label = theme === "system" ? "System" : theme === "light" ? "Light" : "Dark"
  const Icon = theme === "system" ? Monitor : resolvedTheme === "dark" ? Moon : Sun

  return (
    <button
      onClick={cycle}
      className="flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-card text-muted-foreground hover:text-foreground hover:bg-accent transition-all"
      title={`Theme: ${label}. Click to cycle.`}
      aria-label={`Switch theme. Current: ${label}`}
    >
      <Icon className="h-4 w-4" />
    </button>
  )
}

/** Wider toggle with label for the sidebar footer */
export function ThemeToggleSidebar() {
  const { theme, setTheme, resolvedTheme } = useTheme()
  const [mounted, setMounted] = useState(false)

  useEffect(() => setMounted(true), [])
  if (!mounted) {
    return (
      <div className="flex w-full items-center gap-2.5 px-2.5 py-2">
        <div className="h-7 w-7 rounded-md bg-secondary animate-pulse" />
        <div className="h-3 w-12 rounded bg-secondary animate-pulse" />
      </div>
    )
  }

  const cycle = () => {
    document.documentElement.classList.add("transitioning")
    setTimeout(() => document.documentElement.classList.remove("transitioning"), 350)

    if (theme === "system") setTheme("light")
    else if (theme === "light") setTheme("dark")
    else setTheme("system")
  }

  const label = theme === "system" ? "System" : theme === "light" ? "Light" : "Dark"
  const Icon = theme === "system" ? Monitor : resolvedTheme === "dark" ? Moon : Sun

  return (
    <button
      onClick={cycle}
      className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-muted-foreground hover:text-foreground hover:bg-accent transition-all"
      title={`Theme: ${label}. Click to cycle.`}
    >
      <div className="flex h-7 w-7 items-center justify-center rounded-md bg-secondary hover:bg-accent transition-colors">
        <Icon className="h-3.5 w-3.5" />
      </div>
      <span className="text-xs font-medium">{label}</span>
    </button>
  )
}
