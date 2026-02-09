"use client"

import { useState } from "react"
import { Terminal } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { useCatalogData } from "@/lib/catalog-context"

type LogTab = "invocations" | "errors" | "warnings"

export function LogsScreen() {
  const { invocations, validationErrorGroups, validationWarningGroups, stats } = useCatalogData()
  const [activeTab, setActiveTab] = useState<LogTab>("invocations")

  const tabs: { id: LogTab; label: string; count: number }[] = [
    { id: "invocations", label: "Invocations", count: invocations.length },
    { id: "errors", label: "Errors", count: stats.validation_errors },
    { id: "warnings", label: "Warnings", count: stats.validation_warnings },
  ]

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Logs & Events</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {stats.validation_errors} errors &middot; {stats.validation_warnings} warnings &middot; {invocations.length} invocations
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1">
        {tabs.map((tab) => {
          const colors: Record<LogTab, string> = {
            invocations: "hsl(var(--primary))",
            errors: "hsl(var(--destructive))",
            warnings: "hsl(var(--warning))",
          }
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-all ${
                activeTab === tab.id
                  ? "ring-1"
                  : "text-muted-foreground hover:bg-accent hover:text-foreground"
              }`}
              style={
                activeTab === tab.id
                  ? {
                      backgroundColor: `${colors[tab.id]}15`,
                      color: colors[tab.id],
                      boxShadow: `0 0 0 1px ${colors[tab.id]}30`,
                    }
                  : undefined
              }
            >
              {tab.label}
              <span className="text-[10px] tabular-nums opacity-60">{tab.count}</span>
            </button>
          )
        })}
      </div>

      {/* Terminal-style viewer */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-4 py-2.5 bg-secondary/30">
          <div className="flex items-center gap-3">
            <div className="flex gap-1.5">
              <div className="h-2.5 w-2.5 rounded-full bg-[hsl(var(--destructive))]/60" />
              <div className="h-2.5 w-2.5 rounded-full bg-[hsl(var(--warning))]/60" />
              <div className="h-2.5 w-2.5 rounded-full bg-[hsl(var(--success))]/60" />
            </div>
            <div className="flex items-center gap-1.5 ml-1">
              <Terminal className="h-3 w-3 text-muted-foreground" />
              <span className="text-[10px] font-mono text-muted-foreground">agent-logs / {activeTab}</span>
            </div>
          </div>
          <span className="text-[10px] font-mono text-muted-foreground tabular-nums">
            {activeTab === "invocations" ? invocations.length : activeTab === "errors" ? validationErrorGroups.length : validationWarningGroups.length} entries
          </span>
        </div>

        <div className="divide-y divide-border/40 font-mono text-xs">
          {activeTab === "invocations" &&
            invocations.map((inv) => (
              <div
                key={inv.id + inv.ts}
                className="group flex items-start gap-0 px-0 py-0 hover:bg-accent/20 transition-colors"
              >
                <div className="flex items-start justify-end w-10 shrink-0 py-2.5 pr-3 text-[10px] text-muted-foreground/30 select-none border-r border-border/30">
                  {inv.id.slice(0, 4)}
                </div>
                <div className="flex items-start w-36 shrink-0 py-2.5 pl-3 text-[10px] text-muted-foreground/60 tabular-nums">
                  {inv.ts}
                </div>
                <div className="flex-1 py-2.5 pr-4 text-foreground/85 leading-relaxed flex items-center gap-3">
                  <span className="text-[hsl(var(--primary))]">{inv.id}</span>
                  <span className="text-muted-foreground">{inv.wf || "\u2014"}</span>
                  {inv.cmd && (
                    <Badge variant="outline" className="text-[10px] font-normal rounded-md bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))] border-[hsl(var(--primary))]/20 h-4 px-1.5">
                      {inv.cmd}
                    </Badge>
                  )}
                </div>
              </div>
            ))}

          {activeTab === "errors" &&
            validationErrorGroups.map((g) => (
              <div
                key={g.target}
                className="group flex items-start gap-0 px-0 py-0 hover:bg-accent/20 transition-colors"
              >
                <div className="flex items-center justify-center w-16 shrink-0 py-3 border-r border-border/30">
                  <span className="rounded-md px-1.5 py-0.5 text-[10px] font-semibold bg-[hsl(var(--destructive))]/10 text-[hsl(var(--destructive))] tabular-nums">
                    {g.count}
                  </span>
                </div>
                <div className="flex-1 py-3 px-4">
                  <div className="text-sm font-semibold text-foreground">{g.target}</div>
                  <div className="text-muted-foreground mt-0.5 leading-relaxed">{g.sample}</div>
                </div>
              </div>
            ))}

          {activeTab === "warnings" &&
            validationWarningGroups.map((g) => (
              <div
                key={g.target}
                className="group flex items-start gap-0 px-0 py-0 hover:bg-accent/20 transition-colors"
              >
                <div className="flex items-center justify-center w-16 shrink-0 py-3 border-r border-border/30">
                  <span className="rounded-md px-1.5 py-0.5 text-[10px] font-semibold bg-[hsl(var(--warning))]/10 text-[hsl(var(--warning))] tabular-nums">
                    {g.count}
                  </span>
                </div>
                <div className="flex-1 py-3 px-4">
                  <div className="text-sm font-semibold text-foreground">{g.target}</div>
                  <div className="text-muted-foreground mt-0.5 leading-relaxed">{g.sample}</div>
                </div>
              </div>
            ))}
        </div>
      </div>
    </div>
  )
}
