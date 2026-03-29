"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import {
  GitBranch,
  Boxes,
  FileCode,
  MessageSquare,
  Wrench,
  Play,
  ScrollText,
  Database,
  Home,
} from "lucide-react"
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command"
import { useCatalogData } from "@/lib/catalog-context"

interface CommandSearchProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onNavigate: (section: string) => void
}

interface SearchEntry {
  id: string
  label: string
  description: string
  section: string
  group: string
  icon: React.ComponentType<{ className?: string }>
}

export function CommandSearch({ open, onOpenChange, onNavigate }: CommandSearchProps) {
  const { workflows, actions, schemas, prompts, toolFunctions } = useCatalogData()

  const entries = useMemo<SearchEntry[]>(() => {
    const items: SearchEntry[] = []

    // Navigation pages
    const pages = [
      { label: "Home", section: "home", icon: Home, description: "Overview dashboard" },
      { label: "Workflows", section: "workflows", icon: GitBranch, description: "All workflows" },
      { label: "All Actions", section: "actions", icon: Boxes, description: "All actions across workflows" },
      { label: "Runs", section: "runs", icon: Play, description: "Execution history" },
      { label: "Data Explorer", section: "data", icon: Database, description: "Staging and target data" },
      { label: "Schemas", section: "schemas", icon: FileCode, description: "Output schemas" },
      { label: "Prompts", section: "prompts", icon: MessageSquare, description: "Prompt store" },
      { label: "Tools", section: "tools", icon: Wrench, description: "User-defined functions" },
      { label: "Logs", section: "logs", icon: ScrollText, description: "Validation logs and events" },
    ]
    for (const p of pages) {
      items.push({ id: `nav:${p.section}`, label: p.label, description: p.description, section: p.section, group: "Pages", icon: p.icon })
    }

    // Workflows
    for (const wf of workflows) {
      items.push({
        id: `wf:${wf.id}`,
        label: wf.name,
        description: wf.description || `${wf.actionCount} actions`,
        section: "workflows",
        group: "Workflows",
        icon: GitBranch,
      })
    }

    // Actions (Record<string, Action> — key is action name)
    for (const [name, a] of Object.entries(actions)) {
      const kind = a.type === "tool" ? "tool" : "llm"
      items.push({
        id: `action:${a.wf}:${name}`,
        label: name,
        description: a.intent || `${kind} action in ${a.wf}`,
        section: "actions",
        group: "Actions",
        icon: Boxes,
      })
    }

    // Schemas
    for (const s of schemas) {
      const fieldCount = Array.isArray(s.fields) ? s.fields.length : s.fields
      items.push({
        id: `schema:${s.id}`,
        label: s.id,
        description: `${fieldCount} fields`,
        section: "schemas",
        group: "Schemas",
        icon: FileCode,
      })
    }

    // Prompts
    for (const p of prompts) {
      items.push({
        id: `prompt:${p.id}`,
        label: p.name,
        description: p.source || "prompt",
        section: "prompts",
        group: "Prompts",
        icon: MessageSquare,
      })
    }

    // Tools
    for (const t of toolFunctions) {
      items.push({
        id: `tool:${t.name}`,
        label: t.name,
        description: t.sig || "tool function",
        section: "tools",
        group: "Tools",
        icon: Wrench,
      })
    }

    return items
  }, [workflows, actions, schemas, prompts, toolFunctions])

  const handleSelect = useCallback(
    (entry: SearchEntry) => {
      onNavigate(entry.section)
      onOpenChange(false)
    },
    [onNavigate, onOpenChange],
  )

  // Group entries
  const groups = useMemo(() => {
    const order = ["Pages", "Workflows", "Actions", "Schemas", "Prompts", "Tools"]
    const grouped = new Map<string, SearchEntry[]>()
    for (const e of entries) {
      const list = grouped.get(e.group) || []
      list.push(e)
      grouped.set(e.group, list)
    }
    return order.filter((g) => grouped.has(g)).map((g) => ({ name: g, items: grouped.get(g)! }))
  }, [entries])

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange}>
      <CommandInput placeholder="Search workflows, actions, schemas, prompts..." />
      <CommandList>
        <CommandEmpty>No results found.</CommandEmpty>
        {groups.map((group, gi) => (
          <div key={group.name}>
            {gi > 0 && <CommandSeparator />}
            <CommandGroup heading={group.name}>
              {group.items.map((entry) => (
                <CommandItem
                  key={entry.id}
                  value={`${entry.label} ${entry.description}`}
                  onSelect={() => handleSelect(entry)}
                >
                  <entry.icon className="h-4 w-4 text-muted-foreground" />
                  <div className="flex flex-col">
                    <span>{entry.label}</span>
                    <span className="text-xs text-muted-foreground truncate max-w-[400px]">
                      {entry.description}
                    </span>
                  </div>
                </CommandItem>
              ))}
            </CommandGroup>
          </div>
        ))}
      </CommandList>
    </CommandDialog>
  )
}

/**
 * Hook to manage command search open state with keyboard shortcuts.
 * Listens for "/" and Cmd+K / Ctrl+K.
 */
export function useCommandSearch() {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      // Cmd+K or Ctrl+K
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        setOpen((prev) => !prev)
        return
      }
      // "/" when not in an input/textarea
      if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes((e.target as HTMLElement)?.tagName)) {
        e.preventDefault()
        setOpen(true)
      }
    }

    document.addEventListener("keydown", onKeyDown)
    return () => document.removeEventListener("keydown", onKeyDown)
  }, [])

  return { open, setOpen }
}
