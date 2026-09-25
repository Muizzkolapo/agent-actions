"use client"

import { useState, useCallback, useEffect } from "react"
import { AppSidebar } from "@/components/app-sidebar"
import { CommandSearch, useCommandSearch } from "@/components/command-search"
import { HomeScreen } from "@/components/screens/home-screen"
import { WorkflowsScreen } from "@/components/screens/workflows-screen"
import { ActionsScreen } from "@/components/screens/actions-screen"
import { RunsScreen } from "@/components/screens/runs-screen"
import { DataScreen } from "@/components/screens/data-screen"
import { LogsScreen, type LogsIntent } from "@/components/screens/logs-screen"
import { PromptsScreen, SchemasScreen, ToolsScreen } from "@/components/screens/catalog-screens"
import { useCatalog, useCatalogRetry, useCatalogData } from "@/lib/catalog-context"
import { AlertTriangle, PanelLeft, RefreshCw, Loader2 } from "lucide-react"
import { ThemeToggle } from "@/components/theme-toggle"

const SECTION_TITLES: Record<string, string> = {
  home: "Home",
  workflows: "Workflows",
  actions: "All Actions",
  runs: "Runs",
  data: "Data Explorer",
  schemas: "Schemas",
  prompts: "Prompts",
  tools: "Tools",
  logs: "Logs & Events",
}

/** `#ev=<id>` names an event, which only the Logs screen can show. */
function sectionFromHash(): string | null {
  if (typeof window === "undefined") return null
  return /[#&]ev=/.test(window.location.hash) ? "logs" : null
}

export default function Page() {
  const catalogState = useCatalog()

  if (catalogState.status === "loading") return <LoadingSkeleton />
  if (catalogState.status === "error") return <ErrorState message={catalogState.message} />

  return <Dashboard />
}

function Dashboard() {
  const [activeSection, setActiveSection] = useState(() => sectionFromHash() ?? "home")
  const [navKeys, setNavKeys] = useState<Record<string, number>>({})
  const [collapsed, setCollapsed] = useState(false)
  const [logsIntent, setLogsIntent] = useState<LogsIntent | null>(null)
  const { workflows, projectName: catalogProjectName, generatedAt } = useCatalogData()
  const { open: searchOpen, setOpen: setSearchOpen } = useCommandSearch()

  // Re-clicking the active sidebar item resets that screen's drill-down state
  const handleNavigate = useCallback((section: string) => {
    setLogsIntent(null)
    setActiveSection((prev) => {
      if (section === prev) setNavKeys((nk) => ({ ...nk, [section]: (nk[section] || 0) + 1 }))
      return section
    })
  }, [])

  const openLogs = useCallback((intent: LogsIntent) => {
    setLogsIntent(intent)
    setActiveSection("logs")
    setNavKeys((nk) => ({ ...nk, logs: (nk.logs || 0) + 1 }))
  }, [])

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== "[" || e.metaKey || e.ctrlKey || e.altKey) return
      const tag = (e.target as HTMLElement | null)?.tagName
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return
      e.preventDefault()
      setCollapsed((c) => !c)
    }
    document.addEventListener("keydown", onKeyDown)
    return () => document.removeEventListener("keydown", onKeyDown)
  }, [])

  // Project name from catalog metadata (set by the generator from the directory
  // name). Older catalog.json files predate the field, hence the path heuristic.
  const projectName = catalogProjectName || (() => {
    if (workflows.length === 0) return "project"
    const p = workflows[0].path || ""
    const parts = p.replace(/\\/g, "/").split("/").filter(Boolean)
    const artefactIdx = parts.indexOf("artefact")
    if (artefactIdx > 0) return parts[artefactIdx - 1]
    const agentCfgIdx = parts.indexOf("agent_config")
    if (agentCfgIdx > 0) return parts[agentCfgIdx - 1]
    return parts[0] || "project"
  })()

  const generatedDate = generatedAt ? generatedAt.split("T")[0] : ""

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background text-foreground">
      <AppSidebar
        activeSection={activeSection}
        collapsed={collapsed}
        onNavigate={handleNavigate}
        onSearchClick={() => setSearchOpen(true)}
        onShowErrors={() => openLogs({ level: "error" })}
        projectName={projectName}
      />
      <CommandSearch open={searchOpen} onOpenChange={setSearchOpen} onNavigate={handleNavigate} />

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="flex h-11 shrink-0 items-center gap-2.5 border-b border-border px-5">
          <button
            onClick={() => setCollapsed((c) => !c)}
            title="Toggle sidebar  ["
            aria-label="Toggle sidebar"
            className="-ml-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-control text-muted-foreground hover:bg-hover hover:text-foreground"
          >
            <PanelLeft className="h-4 w-4" />
          </button>
          <span className="h-4 w-px bg-border" />
          <span className="text-sm font-medium text-foreground">{SECTION_TITLES[activeSection]}</span>
          {activeSection !== "home" && (
            <>
              <span className="text-[12.5px] text-muted-2">/</span>
              <span className="truncate font-mono text-xs text-muted-foreground">{projectName}</span>
            </>
          )}
          <span className="flex-1" />
          {generatedDate && (
            <span className="hidden shrink-0 whitespace-nowrap text-xs text-muted-foreground sm:inline">
              Generated {generatedDate}
            </span>
          )}
          <ThemeToggle />
        </header>

        <main className="flex-1 overflow-y-auto overflow-x-hidden px-8 pb-14 pt-6">
          {activeSection === "home" && <HomeScreen onNavigate={handleNavigate} onOpenLogs={openLogs} />}
          {activeSection === "workflows" && <WorkflowsScreen key={navKeys.workflows} onOpenLogs={openLogs} />}
          {activeSection === "actions" && <ActionsScreen key={navKeys.actions} onOpenLogs={openLogs} />}
          {activeSection === "runs" && <RunsScreen key={navKeys.runs} />}
          {activeSection === "data" && <DataScreen key={navKeys.data} />}
          {activeSection === "logs" && <LogsScreen key={navKeys.logs} intent={logsIntent} />}
          {activeSection === "schemas" && <SchemasScreen key={navKeys.schemas} />}
          {activeSection === "prompts" && <PromptsScreen key={navKeys.prompts} />}
          {activeSection === "tools" && <ToolsScreen key={navKeys.tools} />}
        </main>
      </div>
    </div>
  )
}

function LoadingSkeleton() {
  return (
    <div className="flex h-screen bg-background">
      <div className="flex w-[252px] flex-col gap-6 border-r border-border p-3.5">
        <div className="flex items-center gap-2.5">
          <div className="h-8 w-8 animate-pulse rounded-control bg-surface-2" />
          <div className="flex flex-col gap-1">
            <div className="h-3 w-24 animate-pulse rounded-sm bg-surface-2" />
            <div className="h-2 w-16 animate-pulse rounded-sm bg-surface-2" />
          </div>
        </div>
        <div className="flex flex-col gap-1">
          {Array.from({ length: 9 }).map((_, i) => (
            <div key={i} className="h-8 animate-pulse rounded-control bg-surface-2" style={{ opacity: 1 - i * 0.08 }} />
          ))}
        </div>
      </div>
      <div className="flex flex-1 flex-col">
        <div className="h-11 border-b border-border" />
        <div className="flex flex-col gap-3.5 px-8 pt-6">
          <div className="flex items-center gap-3">
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            <span className="text-sm text-muted-foreground">Loading catalog…</span>
          </div>
          <div className="grid grid-cols-4 gap-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-24 animate-pulse rounded-card bg-surface" />
            ))}
          </div>
          <div className="h-64 animate-pulse rounded-card bg-surface" />
        </div>
      </div>
    </div>
  )
}

function ErrorState({ message }: { message: string }) {
  const retry = useCatalogRetry()

  return (
    <div className="flex h-screen items-center justify-center bg-background px-6">
      <div className="flex max-w-md flex-col items-center gap-5 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-card border border-border bg-danger-a12">
          <AlertTriangle className="h-5 w-5 text-danger-t" />
        </div>
        <div>
          <h1 className="text-xl font-semibold text-foreground">Catalog not available</h1>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{message}</p>
        </div>
        <div className="w-full rounded-card border border-border bg-surface p-4 text-left">
          <div className="text-xs font-medium text-muted-foreground">Quick fix</div>
          <div className="mt-2 rounded-control border border-border-soft bg-well px-3 py-2 font-mono text-xs text-foreground-2">
            <span className="text-muted-foreground">$ </span>agac docs
          </div>
        </div>
        <button
          onClick={retry}
          className="flex items-center gap-2 rounded-control bg-primary px-4 py-2 text-sm font-medium text-on-primary hover:bg-primary-hover"
        >
          <RefreshCw className="h-4 w-4" />
          Retry
        </button>
      </div>
    </div>
  )
}
