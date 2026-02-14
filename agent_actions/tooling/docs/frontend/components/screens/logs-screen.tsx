"use client"

import { useState } from "react"
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
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight text-foreground">Logs & Events</h1>
        <p className="text-xs text-muted-foreground mt-0.5">
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

      {/* Table */}
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        {activeTab === "invocations" && (
          <table className="w-full dense-table">
            <thead>
              <tr>
                <th className="text-left w-16">ID</th>
                <th className="text-left w-48">Timestamp</th>
                <th className="text-left">Invocation</th>
                <th className="text-left">Workflow</th>
                <th className="text-left w-20">Type</th>
              </tr>
            </thead>
            <tbody>
              {invocations.map((inv) => (
                <tr key={inv.id + inv.ts} className="hover:bg-accent/30 transition-colors">
                  <td className="font-mono text-muted-foreground tabular-nums">{inv.id.slice(0, 4)}</td>
                  <td className="font-mono text-muted-foreground tabular-nums text-[11px]">{inv.ts}</td>
                  <td className="font-mono text-[hsl(var(--primary))]">{inv.id}</td>
                  <td className="text-muted-foreground">{inv.wf || "\u2014"}</td>
                  <td>
                    {inv.cmd ? (
                      <Badge variant="outline" className="text-[10px] font-normal rounded px-1.5 py-0 h-4 bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))] border-[hsl(var(--primary))]/20">
                        {inv.cmd}
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground">&mdash;</span>
                    )}
                  </td>
                </tr>
              ))}
              {invocations.length === 0 && (
                <tr>
                  <td colSpan={5} className="text-center text-muted-foreground py-8">No invocations recorded</td>
                </tr>
              )}
            </tbody>
          </table>
        )}

        {activeTab === "errors" && (
          <table className="w-full dense-table">
            <thead>
              <tr>
                <th className="text-center w-16">Count</th>
                <th className="text-left">Target</th>
                <th className="text-left">Sample Message</th>
              </tr>
            </thead>
            <tbody>
              {validationErrorGroups.map((g) => (
                <tr key={g.target} className="hover:bg-accent/30 transition-colors">
                  <td className="text-center">
                    <span className="inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold bg-[hsl(var(--destructive))]/10 text-[hsl(var(--destructive))] tabular-nums">
                      {g.count}
                    </span>
                  </td>
                  <td className="font-mono font-medium text-foreground">{g.target}</td>
                  <td className="text-muted-foreground max-w-[400px] truncate">{g.sample}</td>
                </tr>
              ))}
              {validationErrorGroups.length === 0 && (
                <tr>
                  <td colSpan={3} className="text-center text-muted-foreground py-8">No errors</td>
                </tr>
              )}
            </tbody>
          </table>
        )}

        {activeTab === "warnings" && (
          <table className="w-full dense-table">
            <thead>
              <tr>
                <th className="text-center w-16">Count</th>
                <th className="text-left">Target</th>
                <th className="text-left">Sample Message</th>
              </tr>
            </thead>
            <tbody>
              {validationWarningGroups.map((g) => (
                <tr key={g.target} className="hover:bg-accent/30 transition-colors">
                  <td className="text-center">
                    <span className="inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold bg-[hsl(var(--warning))]/10 text-[hsl(var(--warning))] tabular-nums">
                      {g.count}
                    </span>
                  </td>
                  <td className="font-mono font-medium text-foreground">{g.target}</td>
                  <td className="text-muted-foreground max-w-[400px] truncate">{g.sample}</td>
                </tr>
              ))}
              {validationWarningGroups.length === 0 && (
                <tr>
                  <td colSpan={3} className="text-center text-muted-foreground py-8">No warnings</td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
