"use client"

import { useState, useCallback } from "react"
import { SidebarProvider, SidebarInset, SidebarTrigger } from "@/components/ui/sidebar"
import { AppSidebar } from "@/components/app-sidebar"
import { CommandSearch, useCommandSearch } from "@/components/command-search"
import { HomeScreen } from "@/components/screens/home-screen"
import { WorkflowsScreen } from "@/components/screens/workflows-screen"
import { ActionsScreen } from "@/components/screens/actions-screen"
import { RunsScreen } from "@/components/screens/runs-screen"
import { DataScreen } from "@/components/screens/data-screen"
import { LogsScreen } from "@/components/screens/logs-screen"
import { PromptsScreen, SchemasScreen, ToolsScreen } from "@/components/screens/catalog-screens"
import { Separator } from "@/components/ui/separator"
import { useCatalog, useCatalogRetry, useCatalogData } from "@/lib/catalog-context"
import { AlertTriangle, RefreshCw, Zap, Loader2 } from "lucide-react"
import { ThemeToggle } from "@/components/theme-toggle"

export default function Page() {
  const catalogState = useCatalog()

  if (catalogState.status === "loading") return <LoadingSkeleton />
  if (catalogState.status === "error") return <ErrorState message={catalogState.message} />

  return <Dashboard />
}

function Dashboard() {
  const [activeSection, setActiveSection] = useState("home")
  const [navKeys, setNavKeys] = useState<Record<string, number>>({})
  const { workflows, projectName: catalogProjectName } = useCatalogData()
  const { open: searchOpen, setOpen: setSearchOpen } = useCommandSearch()

  // Reset drill-down state when re-clicking the same sidebar item
  const handleNavigate = useCallback((section: string) => {
    setActiveSection((prev) => {
      if (section === prev) setNavKeys((nk) => ({ ...nk, [section]: (nk[section] || 0) + 1 }))
      return section === prev ? prev : section
    })
  }, [])

  // Project name from catalog metadata (set by generator from directory name).
  // Falls back to path heuristic for older catalog.json files without the field.
  const projectName = catalogProjectName ?? (() => {
    if (workflows.length === 0) return "project"
    const p = workflows[0].path || ""
    const parts = p.replace(/\\/g, "/").split("/").filter(Boolean)
    const artefactIdx = parts.indexOf("artefact")
    if (artefactIdx > 0) return parts[artefactIdx - 1]
    const agentCfgIdx = parts.indexOf("agent_config")
    if (agentCfgIdx > 0) return parts[agentCfgIdx - 1]
    return parts[0] || "project"
  })()

  const sectionTitles: Record<string, string> = {
    home: "Overview",
    workflows: "Workflows",
    actions: "All Actions",
    runs: "Runs",
    data: "Data Explorer",
    schemas: "Schemas",
    prompts: "Prompts",
    tools: "Tools",
    logs: "Logs & Events",
  }

  return (
    <SidebarProvider>
      <AppSidebar activeSection={activeSection} onNavigate={handleNavigate} onSearchClick={() => setSearchOpen(true)} projectName={projectName} />
      <CommandSearch open={searchOpen} onOpenChange={setSearchOpen} onNavigate={handleNavigate} />
      <SidebarInset>
        <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border bg-background/80 backdrop-blur-md px-4 sticky top-0 z-10">
          <SidebarTrigger className="-ml-1 h-7 w-7 text-muted-foreground hover:text-foreground transition-colors" />
          <Separator orientation="vertical" className="mr-2 h-4 bg-border/50" />
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-foreground tracking-tight">{sectionTitles[activeSection]}</span>
            {activeSection !== "home" && (
              <span className="text-[10px] font-mono text-muted-foreground/50 hidden sm:inline">
                / {projectName}
              </span>
            )}
          </div>
          <div className="ml-auto flex items-center gap-3">
            <div className="hidden sm:flex items-center gap-2 rounded-lg bg-secondary/60 px-3 py-1.5">
              <span className="text-[10px] font-mono font-medium text-foreground">{projectName}</span>
            </div>
            <ThemeToggle />
          </div>
        </header>
        <main className="flex-1 overflow-auto p-6">
          {activeSection === "home" && <HomeScreen onNavigate={handleNavigate} />}
          {activeSection === "workflows" && <WorkflowsScreen key={navKeys.workflows} />}
          {activeSection === "actions" && <ActionsScreen key={navKeys.actions} />}
          {activeSection === "runs" && <RunsScreen key={navKeys.runs} />}
          {activeSection === "data" && <DataScreen key={navKeys.data} />}
          {activeSection === "logs" && <LogsScreen key={navKeys.logs} />}
          {activeSection === "schemas" && <SchemasScreen key={navKeys.schemas} />}
          {activeSection === "prompts" && <PromptsScreen key={navKeys.prompts} />}
          {activeSection === "tools" && <ToolsScreen key={navKeys.tools} />}
        </main>
      </SidebarInset>
    </SidebarProvider>
  )
}

function LoadingSkeleton() {
  return (
    <div className="flex h-screen bg-background">
      <div className="w-64 border-r border-border bg-card/50 p-4 flex flex-col gap-6">
        <div className="flex items-center gap-2">
          <div className="h-8 w-8 rounded-lg bg-secondary animate-pulse" />
          <div className="flex flex-col gap-1">
            <div className="h-3 w-24 rounded bg-secondary animate-pulse" />
            <div className="h-2 w-16 rounded bg-secondary animate-pulse" />
          </div>
        </div>
        <div className="flex flex-col gap-2">
          {Array.from({ length: 7 }).map((_, i) => (
            <div key={i} className="h-8 rounded-lg bg-secondary animate-pulse" style={{ opacity: 1 - i * 0.1 }} />
          ))}
        </div>
      </div>
      <div className="flex-1 p-6 flex flex-col gap-6">
        <div className="h-12 border-b border-border" />
        <div className="flex items-center gap-3">
          <Loader2 className="h-5 w-5 text-[hsl(var(--primary))] animate-spin" />
          <span className="text-sm text-muted-foreground">Loading catalog...</span>
        </div>
        <div className="grid grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-32 rounded-xl bg-secondary/50 animate-pulse" />
          ))}
        </div>
        <div className="h-64 rounded-xl bg-secondary/30 animate-pulse" />
      </div>
    </div>
  )
}

function ErrorState({ message }: { message: string }) {
  const retry = useCatalogRetry()

  return (
    <div className="flex h-screen items-center justify-center bg-background">
      <div className="flex flex-col items-center gap-6 max-w-md text-center">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-[hsl(var(--destructive))]/10 ring-1 ring-[hsl(var(--destructive))]/20">
          <AlertTriangle className="h-8 w-8 text-[hsl(var(--destructive))]" />
        </div>
        <div>
          <h1 className="text-xl font-semibold text-foreground">Catalog Not Available</h1>
          <p className="text-sm text-muted-foreground mt-2 leading-relaxed">{message}</p>
        </div>
        <div className="rounded-xl border border-border bg-card p-4 w-full shadow-sm">
          <div className="flex items-center gap-2 mb-2">
            <Zap className="h-4 w-4 text-[hsl(var(--primary))]" />
            <span className="text-xs font-medium text-foreground">Quick fix</span>
          </div>
          <div className="rounded-lg bg-secondary/50 p-3 font-mono text-xs text-muted-foreground">
            <span className="text-[hsl(var(--primary))]">$</span> agac docs generate
          </div>
        </div>
        <button
          onClick={retry}
          className="flex items-center gap-2 rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background hover:opacity-90 transition-opacity"
        >
          <RefreshCw className="h-4 w-4" />
          Retry
        </button>
      </div>
    </div>
  )
}
