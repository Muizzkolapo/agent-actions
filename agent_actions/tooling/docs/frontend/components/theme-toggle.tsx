"use client"

import { useTheme } from "next-themes"
import { useEffect, useState } from "react"
import { Sun, Moon, Monitor } from "lucide-react"

/** Three-state cycle: System → Light → Dark. */
export function ThemeToggle() {
  const { theme, setTheme, resolvedTheme } = useTheme()
  const [mounted, setMounted] = useState(false)

  useEffect(() => setMounted(true), [])
  if (!mounted) {
    return <div className="h-7 w-7 shrink-0 animate-pulse rounded-control bg-surface-2" />
  }

  const cycle = () => {
    if (theme === "system") setTheme("light")
    else if (theme === "light") setTheme("dark")
    else setTheme("system")
  }

  const label = theme === "system" ? "System" : theme === "light" ? "Light" : "Dark"
  const Icon = theme === "system" ? Monitor : resolvedTheme === "dark" ? Moon : Sun

  return (
    <button
      onClick={cycle}
      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-control border border-border bg-surface text-muted-foreground hover:bg-hover hover:text-foreground"
      title={`Theme: ${label}. Click to cycle.`}
      aria-label={`Switch theme. Current: ${label}`}
    >
      <Icon className="h-[15px] w-[15px]" />
    </button>
  )
}
