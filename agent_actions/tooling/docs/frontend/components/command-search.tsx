"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import * as DialogPrimitive from "@radix-ui/react-dialog"
import { Command } from "cmdk"
import { Search } from "lucide-react"
import { useCatalogData } from "@/lib/catalog-context"
import { Kbd } from "@/components/graphite"

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
  /** Two or three characters — the type, not an icon. */
  tag: string
  tagClass: string
}

const GROUP_ORDER = ["Pages", "Workflows", "Actions", "Schemas", "Prompts", "Tools"]

export function CommandSearch({ open, onOpenChange, onNavigate }: CommandSearchProps) {
  const { workflows, actions, schemas, prompts, toolFunctions } = useCatalogData()

  const entries = useMemo<SearchEntry[]>(() => {
    const items: SearchEntry[] = []
    const neutral = "bg-surface-2 text-muted-foreground"

    const pages = [
      { label: "Home", section: "home", description: "Health at a glance" },
      { label: "Workflows", section: "workflows", description: "All workflows" },
      { label: "All Actions", section: "actions", description: "Every action definition" },
      { label: "Runs", section: "runs", description: "Execution history" },
      { label: "Data Explorer", section: "data", description: "Stored records" },
      { label: "Schemas", section: "schemas", description: "Output contracts" },
      { label: "Prompts", section: "prompts", description: "Prompt store" },
      { label: "Tools", section: "tools", description: "User-defined functions" },
      { label: "Logs", section: "logs", description: "Event stream" },
    ]
    for (const p of pages) {
      items.push({
        id: `nav:${p.section}`,
        label: p.label,
        description: p.description,
        section: p.section,
        group: "Pages",
        tag: "GO",
        tagClass: neutral,
      })
    }

    for (const wf of workflows) {
      items.push({
        id: `wf:${wf.id}`,
        label: wf.name,
        description: wf.description || `${wf.actionCount} actions`,
        section: "workflows",
        group: "Workflows",
        tag: "WF",
        tagClass: neutral,
      })
    }

    for (const [key, a] of Object.entries(actions)) {
      const shortName = key.split("/").pop() ?? key
      items.push({
        id: `action:${key}`,
        label: shortName,
        description: a.intent || `${a.type} action in ${a.wf}`,
        section: "actions",
        group: "Actions",
        tag: a.type === "tool" ? "TOOL" : "LLM",
        tagClass: a.type === "tool" ? "bg-tool/[0.08] text-tool-t" : "bg-llm/10 text-llm-t",
      })
    }

    for (const s of schemas) {
      const fieldCount = Array.isArray(s.fields) ? s.fields.length : s.fields
      items.push({
        id: `schema:${s.id}`,
        label: s.id,
        description: `${fieldCount} field${fieldCount === 1 ? "" : "s"}`,
        section: "schemas",
        group: "Schemas",
        tag: "SCH",
        tagClass: neutral,
      })
    }

    for (const p of prompts) {
      items.push({
        id: `prompt:${p.id}`,
        label: p.name,
        description: p.source || "prompt",
        section: "prompts",
        group: "Prompts",
        tag: "PRM",
        tagClass: neutral,
      })
    }

    for (const t of toolFunctions) {
      items.push({
        id: `tool:${t.name}`,
        label: t.name,
        description: t.sig || "tool function",
        section: "tools",
        group: "Tools",
        tag: "FN",
        tagClass: neutral,
      })
    }

    return items
  }, [workflows, actions, schemas, prompts, toolFunctions])

  const groups = useMemo(() => {
    const grouped = new Map<string, SearchEntry[]>()
    for (const e of entries) {
      const list = grouped.get(e.group)
      if (list) list.push(e)
      else grouped.set(e.group, [e])
    }
    return GROUP_ORDER.filter((g) => grouped.has(g)).map((g) => ({ name: g, items: grouped.get(g)! }))
  }, [entries])

  const handleSelect = useCallback(
    (entry: SearchEntry) => {
      onNavigate(entry.section)
      onOpenChange(false)
    },
    [onNavigate, onOpenChange],
  )

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/55 backdrop-blur-[4px] data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <DialogPrimitive.Content className="fixed left-1/2 top-[11vh] z-50 flex w-[min(640px,92vw)] -translate-x-1/2 flex-col overflow-hidden rounded-card border border-border-2 bg-surface data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=open]:slide-in-from-top-2">
          <DialogPrimitive.Title className="sr-only">Jump to</DialogPrimitive.Title>
          <Command className="flex flex-col overflow-hidden" loop>
            <div className="flex items-center gap-2.5 border-b border-border px-4">
              <Search className="h-[15px] w-[15px] shrink-0 text-muted-foreground" strokeWidth={2.2} />
              <Command.Input
                placeholder="Jump to a workflow, action, prompt, schema or page…"
                className="h-[52px] min-w-0 flex-1 border-0 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
              />
              <Kbd>esc</Kbd>
            </div>
            <Command.List className="max-h-[min(420px,52vh)] overflow-y-auto p-1.5">
              <Command.Empty className="px-2.5 py-8 text-center text-[12.5px] text-muted-foreground">
                Nothing matches that search
              </Command.Empty>
              {groups.map((group) => (
                <Command.Group
                  key={group.name}
                  heading={group.name}
                  className="[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-2.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-2"
                >
                  {group.items.map((entry) => (
                    <Command.Item
                      key={entry.id}
                      value={`${entry.label} ${entry.description}`}
                      onSelect={() => handleSelect(entry)}
                      className="flex cursor-pointer items-center gap-2.5 rounded-control px-2.5 py-1.5 data-[selected=true]:bg-selected"
                    >
                      <span
                        className={`flex h-6 w-[30px] shrink-0 items-center justify-center rounded-control font-mono text-[9px] font-bold ${entry.tagClass}`}
                      >
                        {entry.tag}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-mono text-[12.5px] text-foreground">
                          {entry.label}
                        </span>
                        <span className="mt-px block truncate text-[11px] text-muted-foreground">
                          {entry.description}
                        </span>
                      </span>
                    </Command.Item>
                  ))}
                </Command.Group>
              ))}
            </Command.List>
            <div className="flex items-center gap-4 border-t border-border bg-surface-2 px-4 py-2 text-[10.5px] text-muted-foreground">
              <span className="flex items-center gap-1"><Kbd>↑</Kbd><Kbd>↓</Kbd>navigate</span>
              <span className="flex items-center gap-1"><Kbd>↵</Kbd>open</span>
              <span className="flex items-center gap-1"><Kbd>/</Kbd>open anywhere</span>
              <span className="flex-1" />
              <span className="font-mono">{entries.length.toLocaleString()} items</span>
            </div>
          </Command>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}

/** Opens on ⌘K / Ctrl+K, and on "/" outside a text field. */
export function useCommandSearch() {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        setOpen((prev) => !prev)
        return
      }
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
